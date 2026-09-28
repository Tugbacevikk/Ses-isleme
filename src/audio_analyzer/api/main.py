import logging
import os
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# Windows SYMLINK ve SpeechBrain önbellek uyarılarını bastır
warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.api import dependencies, metrics
from audio_analyzer.api.routers import jobs

from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("speechbrain.utils.fetching").setLevel(logging.ERROR)
logging.getLogger("speechbrain.utils.parameter_transfer").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Uygulama Yaşam Döngüsü (Lifespan).
    Üretim (PostgreSQL) ortamlarında tek şema kaynağı Alembic'tir.
    `create_all` yalnızca yerel SQLite dev/test modunda tabloları otomatik oluşturur.
    """
    from audio_analyzer.adapters.storage.storage_factory import assert_storage_shared_across_processes

    assert_storage_shared_across_processes()

    allow_fallback = os.getenv("ALLOW_SQLITE_FALLBACK", "false").lower() == "true"
    db_is_sqlite = "sqlite" in str(dependencies.engine.url)

    try:
        from sqlalchemy import text

        async with dependencies.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        if db_is_sqlite:
            async with dependencies.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
    except Exception as db_err:
        if allow_fallback and not db_is_sqlite:
            logger.warning("PostgreSQL bağlantısı başarısız, ALLOW_SQLITE_FALLBACK aktif. SQLite'a geçiliyor... Hata: %s", db_err)
            fallback_url = "sqlite:///storage/dev_database.db"
            dependencies.engine = dependencies.create_async_db_engine(fallback_url)
            dependencies.AsyncSessionLocal.configure(bind=dependencies.engine)
            dependencies.SessionLocal = dependencies.AsyncSessionLocal
            async with dependencies.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        elif db_is_sqlite:
            logger.warning("SQLite tablo oluşturma uyarısı: %s", db_err)
        else:
            logger.error("PostgreSQL bağlantı hatası: %s", db_err)

    try:
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline

        get_shared_pipeline()
    except Exception as e:
        logger.warning("Model ön yükleme uyarısı: %s", e)

    yield


app = FastAPI(
    title="Ses Analizi Platformu (STT + Speaker Diarization)",
    description="Gelişmiş Ses Analizi ve Konuşmacı Ayrıştırma Platformu Web Arayüzü",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware (Kurumsal Üçüncü Parti İstemci Desteği)
allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# APIRouter Kaydı
app.include_router(jobs.router)
app.include_router(metrics.router)

# Statik Dosya Hizmeti
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
def get_web_ui():
    """
    Sürükle-Bırak Kolay Ses Analiz Web Arayüzü (Statik Frontend Dosyasından Sunulur).
    """
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Web arayüzü dosyası bulunamadı")
    return FileResponse(index_path)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Tarayıcıların otomatik favicon isteğine 204 No Content dönerek 404 loglarını engeller.
    """
    return Response(status_code=204)


@app.get("/health")
async def health_check():
    """
    Sistem Sağlık ve Kullanılabilirlik (Liveness Probe) Kontrolü.
    """
    db_status = "OK"
    try:
        from sqlalchemy import text

        async with dependencies.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("Health check database connection error: %s", e, exc_info=True)
        db_status = "ERROR"

    is_healthy = db_status == "OK"
    return Response(
        content=f'{{"status": "{ "HEALTHY" if is_healthy else "UNHEALTHY" }", "database": "{db_status}"}}',
        media_type="application/json",
        status_code=200 if is_healthy else 503,
    )


@app.get("/health/ready")
async def readiness_check():
    """
    Kubernetes / Docker Readiness Probe Kontrolü.
    Veritabanı (DB), Redis kuyruğu ve AI Model hazırlık durumunu doğrular.
    """
    import json

    db_ok = False
    redis_ok = False
    model_ok = False

    # 1. DB Kontrolü
    try:
        from sqlalchemy import text

        async with dependencies.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as ex:
        logger.error("Readiness DB kontrol hatası: %s", ex)

    # 2. Redis Kontrolü
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        from audio_analyzer.adapters.messaging.redis_stream_adapter import RedisStreamAdapter
        import redis.asyncio as aioredis

        pool = RedisStreamAdapter.get_pool(redis_url)
        client = aioredis.Redis(connection_pool=pool)
        pong = await client.ping()
        redis_ok = bool(pong)
    except Exception as ex:
        logger.warning("Readiness Redis kontrol uyarısı: %s", ex)

    # 3. Model Yüklü Kontrolü
    try:
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline

        pipe = get_shared_pipeline()
        model_ok = pipe.stt_engine is not None and getattr(pipe.stt_engine, "_model", None) is not None
    except Exception as ex:
        logger.warning("Readiness Model kontrol uyarısı: %s", ex)

    is_ready = db_ok and redis_ok
    status_code = 200 if is_ready else 503

    return Response(
        content=json.dumps(
            {
                "status": "READY" if is_ready else "NOT_READY",
                "database": "OK" if db_ok else "ERROR",
                "redis": "OK" if redis_ok else "ERROR",
                "model_loaded": "OK" if model_ok else "PENDING",
            }
        ),
        media_type="application/json",
        status_code=status_code,
    )


def start():
    """Uvicorn sunucusu üzerinden FastAPI API'sini başlatır."""
    import uvicorn

    reload_env = os.getenv("RELOAD", "false").lower() == "true"
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run("audio_analyzer.api.main:app", host=host, port=port, reload=reload_env)


if __name__ == "__main__":
    start()

