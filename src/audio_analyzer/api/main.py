import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.api.dependencies import engine
from audio_analyzer.api.routers import jobs

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Uygulama Yaşam Döngüsü (Lifespan).
    Sunucu başlatılırken veritabanı tablolarını oluşturur ve AI modellerini önceden ısıtır (Warm-load).
    """
    Base.metadata.create_all(bind=engine)

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
def health_check():
    """
    Sistem Sağlık ve Kullanılabilirlik (Liveness/Readiness Probe) Kontrolü.
    Veritabanı bağlantısı ve genel uygulama durumunu kontrol eder.
    """
    db_status = "OK"
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"ERROR: {e}"

    is_healthy = db_status == "OK"
    return Response(
        content=f'{{"status": "{ "HEALTHY" if is_healthy else "UNHEALTHY" }", "database": "{db_status}"}}',
        media_type="application/json",
        status_code=200 if is_healthy else 503,
    )


def start():
    """Uvicorn sunucusu üzerinden FastAPI API'sini başlatır."""
    import uvicorn

    uvicorn.run("audio_analyzer.api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    start()
