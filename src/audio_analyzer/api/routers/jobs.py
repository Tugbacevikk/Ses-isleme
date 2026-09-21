import logging
import mimetypes
import os
import secrets
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from audio_analyzer.adapters.storage.storage_factory import get_storage_adapter
from audio_analyzer.api.dependencies import SessionLocal, get_repository, get_uow
from audio_analyzer.domain.interfaces import ITranscriptRepository
from audio_analyzer.domain.models import JobStatus, TranscriptUtterance
from audio_analyzer.services.job_service import JobService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Jobs & Analysis"])

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    """
    İsteğin X-API-Key başlığını doğrular. Ortam değişkeninde API_KEY tanımlıysa kontrol eder.
    Tanımlı değilse (geliştirme modunda) doğrulama atlanır.
    Timing-attack saldırılarını önlemek için secrets.compare_digest kullanılır.
    """
    expected_api_key = os.getenv("API_KEY")
    if expected_api_key:
        if not api_key or not secrets.compare_digest(api_key, expected_api_key):
            raise HTTPException(
                status_code=401, detail="Geçersiz veya eksik API Anahtarı (X-API-Key header)."
            )
    return api_key


def run_pipeline_background(job_id_str: str, file_name: str, file_bytes: bytes):
    """
    Arka plan asenkron worker fonksiyonu (Non-blocking HTTP 202 mimarisi).
    DB kilitlerini engellemek için transaction'lar kısa süreli tutulur ve 
    uzun süren AI modelleri açık transaction olmadan çalıştırılır.
    """
    try:
        storage = get_storage_adapter()
        record_uuid = uuid.UUID(job_id_str)
        callback_url = None

        # 1. Durumu PROCESSING olarak güncelle ve transaction'ı hemen kapat
        with get_uow() as uow:
            record = uow.repository.get_record_by_id(record_uuid)
            if not record:
                return
            uow.repository.update_status(record_uuid, JobStatus.PROCESSING)
            storage_uri = record.storage_uri
            callback_url = record.callback_url

        # 2. Uzun süren AI Modellerini çalıştır (DB kilidi YOK)
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline

        pipeline = get_shared_pipeline()
        local_audio_path = storage.get_path(storage_uri)

        try:
            utterances, language = pipeline.process(local_audio_path)

            # 3. Sonuçları kaydet (COMPLETED) ve transaction'ı kapat
            with get_uow() as uow:
                uow.repository.save_utterances(record_uuid, utterances, language=language)

            if callback_url:
                from audio_analyzer.services.webhook_service import WebhookService

                webhook_svc = WebhookService()
                payload = {
                    "job_id": job_id_str,
                    "file_name": file_name,
                    "status": "COMPLETED",
                    "language": language,
                    "utterances": [
                        {
                            "speaker_id": u.speaker_id,
                            "start_time": u.start_time,
                            "end_time": u.end_time,
                            "text": u.text,
                        }
                        for u in utterances
                    ],
                }
                webhook_svc.send_callback(callback_url, payload)

        except Exception as ex:
            logger.error("Background pipeline error for job_id=%s: %s", job_id_str, ex, exc_info=True)
            from audio_analyzer.services.job_service import sanitize_error_message

            sanitized_msg = sanitize_error_message(ex)
            with get_uow() as uow:
                uow.repository.update_status(record_uuid, JobStatus.FAILED, error_message=sanitized_msg)

            if callback_url:
                from audio_analyzer.services.webhook_service import WebhookService

                webhook_svc = WebhookService()
                payload = {
                    "job_id": job_id_str,
                    "file_name": file_name,
                    "status": "FAILED",
                    "error_message": sanitized_msg,
                }
                webhook_svc.send_callback(callback_url, payload)

    except Exception as ex:
        logger.error("Background task execution error: %s", ex, exc_info=True)


# --- Schemas ---
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
    language: Optional[str] = None
    error_message: Optional[str] = None
    utterances: List[UtteranceResponse] = []


class UtteranceUpdateRequest(BaseModel):
    speaker_id: str
    text: str


class UtteranceCreateRequest(BaseModel):
    speaker_id: str
    start_time: float
    end_time: float
    text: str


# --- Endpoints ---
@router.post("/analyze", response_model=JobCreateResponse, status_code=202)
async def upload_and_analyze_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    callback_url: Optional[str] = Form(None),
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Ses dosyasını yükler, validasyondan geçirir, PENDING durumuyla kaydeder
    ve analizi ASENKRON başlatır (HTTP 202 Accepted).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Ses dosyası adı boş olamaz.")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen ses formatı '{ext}'. İzin verilen formatlar: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()

    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Yüklenen ses dosyası boş (0 bayt) olamaz.")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya boyutu çok büyük ({len(file_bytes) / (1024 * 1024):.1f} MB). Maksimum izin verilen limit: 100 MB.",
        )

    from audio_analyzer.utils.file_validator import is_valid_audio_content

    if not is_valid_audio_content(file_bytes, file.filename):
        raise HTTPException(
            status_code=400,
            detail="Yüklenen dosya geçerli ve bozulmamış bir ses dosyası içeriği (WAV, MP3, FLAC, M4A, OGG) taşımıyor.",
        )

    storage = get_storage_adapter()
    job_service = JobService(storage=storage, repository=repository)
    job_id = job_service.create_job(file_name=file.filename, file_bytes=file_bytes, callback_url=callback_url)

    use_celery = os.getenv("USE_CELERY", "false").lower() == "true"
    if use_celery:
        try:
            from audio_analyzer.workers.tasks import process_audio_task

            process_audio_task.delay(str(job_id))
        except Exception as e:
            logger.warning("Celery delay dispatch note: %s, falling back to BackgroundTasks", e)
            background_tasks.add_task(
                run_pipeline_background, str(job_id), file.filename, file_bytes
            )
    else:
        background_tasks.add_task(run_pipeline_background, str(job_id), file.filename, file_bytes)

    return JobCreateResponse(
        job_id=str(job_id),
        file_name=file.filename,
        status="PENDING",
        message="Ses analizi görevi asenkron olarak kuyruğa alındı.",
    )


@router.get("/jobs", response_model=List[JobStatusResponse])
def list_jobs(
    skip: int = Query(0, ge=0, description="Atlanacak kayıt sayısı"),
    limit: int = Query(20, ge=1, le=100, description="Getirilecek maksimum kayıt sayısı"),
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Geçmişte yüklenen tüm ses analizi görevlerini tarihe göre tersten sıralı (en yeni en üstte)
    ve sayfalamalı (Pagination: skip, limit) olarak getirir.
    """
    records = repository.list_records(skip=skip, limit=limit)
    return [
        JobStatusResponse(
            job_id=str(r.id),
            file_name=r.file_name,
            status=r.status.value,
            language=r.language,
            error_message=r.error_message,
            utterances=[
                UtteranceResponse(
                    speaker_id=u.speaker_id,
                    start_time=u.start_time,
                    end_time=u.end_time,
                    text=u.text,
                )
                for u in r.utterances
            ],
        )
        for r in records
    ]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Verilen job_id görevinin durumunu ve analiz sonuçlarını getirir.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

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


@router.get("/jobs/{job_id}/audio")
def get_job_audio_file(
    job_id: str,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Ses analizi görevine ait ham ses dosyasını tarayıcıda dinlenmek üzere sunar (Streaming / Audio Player).
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    record = repository.get_record_by_id(record_uuid)

    if not record:
        raise HTTPException(status_code=404, detail="Ses analizi görevi bulunamadı.")

    storage = get_storage_adapter()
    local_path = storage.get_path(record.storage_uri)

    if not os.path.exists(local_path):
        raise HTTPException(status_code=404, detail="Ses dosyası diskte bulunamadı.")

    media_type, _ = mimetypes.guess_type(local_path)
    if not media_type:
        media_type = "audio/wav"

    return FileResponse(path=local_path, media_type=media_type, filename=record.file_name)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Tüm ses analizi görevini, ilişkili veritabanı kayıtlarını ve fiziksel ses dosyasını siler.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    record = repository.get_record_by_id(record_uuid)
    if not record:
        raise HTTPException(status_code=404, detail="Ses analizi görevi bulunamadı.")

    storage = get_storage_adapter()
    try:
        storage.delete(record.storage_uri)
    except Exception as ex:
        logger.warning("File delete note: %s", ex)

    success = repository.delete_record(record_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="Görevi veritabanından silme başarısız.")

    return {"status": "SUCCESS", "message": "Ses analizi kaydı ve dosyası başarıyla silindi."}


@router.put("/jobs/{job_id}/utterances/{utterance_index}")
def update_utterance_speaker(
    job_id: str,
    utterance_index: int,
    req: UtteranceUpdateRequest,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Kullanıcının Arayüzden (UI) manuel olarak konuşmacı etiketini veya metni değiştirmesini sağlar.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    success = repository.update_utterance(
        record_id=record_uuid,
        utterance_index=utterance_index,
        speaker_id=req.speaker_id,
        text=req.text,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Güncellenecek cümle bulunamadı.")

    return {"status": "SUCCESS", "message": "Konuşmacı etiketi başarıyla güncellendi."}


@router.delete("/jobs/{job_id}/utterances/{utterance_index}")
def delete_utterance(
    job_id: str,
    utterance_index: str,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Kullanıcının Arayüzden (UI) seçtiği konuşmacı kartını/kutusunu silmesini sağlar (UUID veya İndeks ile).
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    success = False
    # Önce UUID olarak silmeyi dene
    try:
        utt_uuid = uuid.UUID(utterance_index)
        if hasattr(repository, "delete_utterance_by_id"):
            success = repository.delete_utterance_by_id(record_uuid, utt_uuid)
    except ValueError:
        pass

    # UUID değilse veya bulunamadıysa tamsayı indeksi olarak sil
    if not success:
        try:
            idx = int(utterance_index)
            success = repository.delete_utterance(record_id=record_uuid, utterance_index=idx)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz indeks veya UUID formatı.")

    if not success:
        raise HTTPException(status_code=404, detail="Silinecek cümle bulunamadı.")

    return {"status": "SUCCESS", "message": "Konuşmacı bloğu başarıyla silindi."}


@router.post("/jobs/{job_id}/utterances")
def create_utterance(
    job_id: str,
    req: UtteranceCreateRequest,
    repository: ITranscriptRepository = Depends(get_repository),
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Kullanıcının Arayüzden (UI) yeni bir konuşmacı kartı/kutusu eklemesini sağlar.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    new_u = TranscriptUtterance(
        id=uuid.uuid4(),
        speaker_id=req.speaker_id,
        start_time=req.start_time,
        end_time=req.end_time,
        text=req.text,
    )
    success = repository.add_utterance(record_id=record_uuid, utterance=new_u)
    if not success:
        raise HTTPException(status_code=404, detail="Ses görevi bulunamadı.")

    return {"status": "SUCCESS", "message": "Yeni konuşmacı bloğu başarıyla eklendi."}
