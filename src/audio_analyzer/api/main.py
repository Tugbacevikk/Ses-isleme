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
from audio_analyzer.api.dependencies import engine
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
    Sunucu başlatılırken veritabanı tablolarını asenkron olarak oluşturur ve AI modellerini önceden ısıtır (Warm-load).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    Sistem Sağlık ve Kullanılabilirlik (Liveness/Readiness Probe) Kontrolü.
    Veritabanı bağlantısı ve genel uygulama durumunu kontrol eder.
    """
    db_status = "OK"
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
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


def start():
    """Uvicorn sunucusu üzerinden FastAPI API'sini başlatır."""
    import uvicorn

    reload_env = os.getenv("RELOAD", "false").lower() == "true"
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run("audio_analyzer.api.main:app", host=host, port=port, reload=reload_env)


if __name__ == "__main__":
    start()
