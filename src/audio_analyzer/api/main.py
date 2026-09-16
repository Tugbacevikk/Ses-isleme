import uuid
import os
from typing import Dict, Any, List
from dotenv import load_dotenv

# .env dosyasındaki ortam değişkenlerini yükle (Örn: HF_TOKEN)
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.job_service import JobService
from audio_analyzer.domain.models import DeviceConfig, JobStatus

from contextlib import asynccontextmanager

# SQLite/PostgreSQL DB Bağlantısı (Ortam değişkeninden oku)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Uygulama Yaşam Döngüsü (Lifespan).
    Sunucu başlatılırken veritabanı tablolarını oluşturur ve AI modellerini önceden ısıtır (Warm-load).
    Modül import edilirken yan etki oluşmasını engeller.
    """
    # 1. Veritabanı tablolarını oluştur
    Base.metadata.create_all(bind=engine)
    
    # 2. Yapay zeka modellerini önceden ısıt (Warm-loading)
    try:
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline
        get_shared_pipeline()
    except Exception as e:
        print(f"[LIFESPAN UYARI] Model ön yükleme uyarısı: {e}")
    
    yield


# FastAPI Uygulaması
app = FastAPI(
    title="Ses Analizi Platformu (STT + Speaker Diarization)",
    description="Gelişmiş Ses Analizi ve Konuşmacı Ayrıştırma Platformu Web Arayüzü",
    version="1.0.0",
    lifespan=lifespan,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Response Schemas
class JobCreateResponse(BaseModel):
    job_id: str
    file_name: str
    status: str
    message: str


class UtteranceResponse(BaseModel):
    speaker_id: str
    start_time: float
    end_time: float
    text: str


class JobStatusResponse(BaseModel):
    job_id: str
    file_name: str
    status: str
    language: str | None = None
    error_message: str | None = None
    utterances: List[UtteranceResponse] = []


from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
def get_web_ui():
    """
    Sürükle-Bırak Kolay Ses Analiz Web Arayüzü (Statik Frontend Dosyasından Sunulur).
    http://localhost:8000/ adresinde doğrudan açılır.
    """
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Statik frontend dosyası (index.html) bulunamadı.")
    return FileResponse(index_path)


from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks

def run_pipeline_background(job_id_str: str, file_name: str, file_bytes: bytes):
    """
    Arka plan asenkron worker fonksiyonu (Non-blocking HTTP 202 mimarisi).
    Sıcak yüklenmiş (Warm-loaded) önbellekteki tekil yapay zeka pipeline nesnesini kullanır.
    """
    db = SessionLocal()
    try:
        storage = LocalStorageAdapter(base_dir="storage/raw")
        repository = PostgresRepository(session=db)

        # Sıcak yüklenmiş (Warm-loaded) Singleton AI Pipeline
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline
        pipeline = get_shared_pipeline()

        job_service = JobService(storage=storage, repository=repository, pipeline=pipeline)
        job_service.execute_job(uuid.UUID(job_id_str))
    except Exception as ex:
        print(f"Background task execution error: {ex}")
    finally:
        db.close()


from pathlib import Path
from fastapi.security import APIKeyHeader
from typing import Optional

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    """
    İsteğin X-API-Key başlığını doğrular. Ortam değişkeninde API_KEY tanımlıysa kontrol eder.
    Tanımlı değilse (geliştirme modunda) doğrulama atlanır.
    """
    expected_api_key = os.getenv("API_KEY")
    if expected_api_key and api_key != expected_api_key:
        raise HTTPException(
            status_code=401,
            detail="Geçersiz veya eksik API Anahtarı (X-API-Key header)."
        )
    return api_key


ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


@app.post("/api/v1/analyze", response_model=JobCreateResponse, status_code=202)
async def upload_and_analyze_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Ses dosyasını (MP3, WAV, FLAC vb.) yükler, tip ve boyut validasyonundan geçirir,
    PENDING durumuyla kaydeder ve analizi ASENKRON başlatır.
    İstemciye anında HTTP 202 Accepted yanıtı döner (Non-blocking).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Ses dosyası adı boş olamaz.")

    # 1. Dosya Uzantısı Validasyonu
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen ses formatı '{ext}'. İzin verilen formatlar: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    file_bytes = await file.read()

    # 2. Dosya Boyutu Validasyonu
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Yüklenen ses dosyası boş (0 bayt) olamaz.")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya boyutu çok büyük ({len(file_bytes) / (1024 * 1024):.1f} MB). Maksimum izin verilen limit: 100 MB."
        )

    storage = LocalStorageAdapter(base_dir="storage/raw")
    repository = PostgresRepository(session=db)

    job_service = JobService(storage=storage, repository=repository)
    job_id = job_service.create_job(file_name=file.filename, file_bytes=file_bytes)

    # Celery veya FastAPI BackgroundTasks ile Asenkron Tetikleme
    use_celery = os.getenv("USE_CELERY", "false").lower() == "true"
    if use_celery:
        try:
            from audio_analyzer.workers.tasks import process_audio_task
            process_audio_task.delay(str(job_id))
        except Exception as e:
            print(f"Celery delay dispatch note: {e}, falling back to BackgroundTasks")
            background_tasks.add_task(run_pipeline_background, str(job_id), file.filename, file_bytes)
    else:
        background_tasks.add_task(run_pipeline_background, str(job_id), file.filename, file_bytes)

    return JobCreateResponse(
        job_id=str(job_id),
        file_name=file.filename,
        status="PENDING",
        message="Ses analizi görevi asenkron olarak kuyruğa alındı.",
    )


class UtteranceUpdateRequest(BaseModel):
    speaker_id: str
    text: str


@app.put("/api/v1/jobs/{job_id}/utterances/{utterance_index}")
def update_utterance_speaker(
    job_id: str,
    utterance_index: int,
    req: UtteranceUpdateRequest,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Kullanıcının Arayüzden (UI) manuel olarak konuşmacı etiketini veya metni değiştirmesini sağlar.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    repository = PostgresRepository(session=db)
    record = repository.get_record_by_id(record_uuid)

    if not record or not record.utterances:
        raise HTTPException(status_code=404, detail="Ses görevi veya cümleler bulunamadı.")

    if utterance_index < 0 or utterance_index >= len(record.utterances):
        raise HTTPException(status_code=400, detail="Geçersiz cümle indeksi.")

    record.utterances[utterance_index].speaker_id = req.speaker_id
    record.utterances[utterance_index].text = req.text
    db.commit()

    return {"status": "SUCCESS", "message": "Konuşmacı etiketi başarıyla güncellendi."}


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Verilen job_id görevinin durumunu ve analiz sonuçlarını getirir.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    repository = PostgresRepository(session=db)
    record = repository.get_record_by_id(record_uuid)

    if not record:
        raise HTTPException(status_code=404, detail="Ses analizi görevi bulunamadı.")

    utterances = [
        UtteranceResponse(
            speaker_id=u.speaker_id,
            start_time=u.start_time,
            end_time=u.end_time,
            text=u.text,
        )
        for u in record.utterances
    ]

    return JobStatusResponse(
        job_id=str(record.id),
        file_name=record.file_name,
        status=record.status.value,
        language=record.language,
        error_message=record.error_message,
        utterances=utterances,
    )


def start():
    """Uvicorn sunucusu üzerinden FastAPI API'sini başlatır."""
    import uvicorn
    uvicorn.run("audio_analyzer.api.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    start()
