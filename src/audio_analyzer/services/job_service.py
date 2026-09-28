import asyncio
import logging
import re
import uuid
from typing import Optional

from audio_analyzer.domain.interfaces import IAudioStorage, ITranscriptRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.pipeline import AudioAnalysisPipeline

logger = logging.getLogger(__name__)


def sanitize_error_message(ex: Exception) -> str:
    """
    Sistem dosya yollarını, sunucu dizin yapısını ve iç detayları sızdırmamak
    için kullanıcıya dönecek hata mesajını temizler.
    """
    err_type = type(ex).__name__
    err_str = str(ex)

    # Windows ve Unix mutlak dosya yollarını maskele (örn. C:\Users\... veya /var/...)
    err_str = re.sub(r'[A-Za-z]:\\[^\s:]+', '[FILE_PATH]', err_str)
    err_str = re.sub(r'/(?:[^\s:]+/)+[^\s:]+', '[FILE_PATH]', err_str)

    return f"{err_type}: {err_str}"


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class JobService:
    """
    Ses Analiz İşleri ve Görev Yaşam Döngüsü Servisi (Job Lifecycle Service).
    Kullanıcı taleplerini alır, veritabanı durumlarını ve dosya depolamayı yönetir.
    """

    def __init__(
        self,
        storage: IAudioStorage,
        repository: ITranscriptRepository,
        pipeline: Optional[AudioAnalysisPipeline] = None,
    ):
        self.storage = storage
        self.repo = repository
        self.pipeline = pipeline

    async def create_job(self, file_name: str, file_bytes: bytes, callback_url: Optional[str] = None) -> uuid.UUID:
        """
        Yeni bir analiz görevi oluşturur (status='PENDING').
        Ses dosyasını depolamaya kaydeder ve DB kaydını açar.
        """
        storage_uri = await asyncio.to_thread(self.storage.save, file_bytes, file_name)
        record_id = uuid.uuid4()

        record = AudioRecord(
            id=record_id,
            storage_uri=storage_uri,
            file_name=file_name,
            status=JobStatus.PENDING,
            callback_url=callback_url,
        )
        saved = await self.repo.save_record(record)
        return saved.id

    async def execute_job(
        self, record_id: uuid.UUID, file_bytes: Optional[bytes] = None
    ) -> bool:
        """
        Arka plan worker'ı (Celery, RQ, BackgroundTasks) tarafından çağrılır.
        Durumu 'PROCESSING' yapar, pipeline'ı çalıştırır, sonuçları DB'ye kaydeder ('COMPLETED'/'FAILED')
        ve tanımlıysa webhook callback bildirimini tetikler.
        """
        record = await self.repo.get_record_by_id(record_id)
        if not record:
            return False

        # Durumu PROCESSING yap
        await self.repo.update_status(record_id, JobStatus.PROCESSING)

        try:
            import os

            # Pipeline çalıştır (Sıcak Yüklenmiş Singleton)
            if self.pipeline is None:
                from audio_analyzer.services.pipeline_factory import get_shared_pipeline

                self.pipeline = get_shared_pipeline()

            # file_bytes verilmemişse storage'dan oku (Lazy get_bytes / get_path)
            if not file_bytes:
                if hasattr(self.storage, "get_bytes"):
                    try:
                        file_bytes = await asyncio.to_thread(self.storage.get_bytes, record.storage_uri)
                    except Exception as ex:
                        logger.warning("Storage'dan RAM baytları okunamadı (%s): %s", record.storage_uri, ex)

                if not file_bytes:
                    try:
                        p = await asyncio.to_thread(self.storage.get_path, record.storage_uri)
                        if p and os.path.exists(p):
                            file_bytes = await asyncio.to_thread(_read_file, p)
                    except Exception as ex:
                        logger.warning("Dosya diski üzerinden RAM'e okunamadı: %s", ex)

            # RAM tabanlı 0-Disk I/O işleme (process_bytes) ile güvenli fallback (Non-blocking Thread)
            if file_bytes and hasattr(self.pipeline, "process_bytes"):
                try:
                    utterances, language, overlap_summary = await asyncio.to_thread(
                        self.pipeline.process_bytes, file_bytes
                    )
                except Exception as p_err:
                    logger.warning("RAM (process_bytes) işleme uyarısı (%s), disk path yöntemine düşülüyor.", p_err)
                    local_path = await asyncio.to_thread(self.storage.get_path, record.storage_uri)
                    utterances, language, overlap_summary = await asyncio.to_thread(
                        self.pipeline.process, local_path
                    )
            else:
                local_path = await asyncio.to_thread(self.storage.get_path, record.storage_uri)
                utterances, language, overlap_summary = await asyncio.to_thread(
                    self.pipeline.process, local_path
                )

            # Başarılı ise sonuçları ve dili kaydet (COMPLETED)
            await self.repo.save_utterances(record_id, utterances, language=language)

            # Webhook callback tanımlıysa gönder
            if record.callback_url:
                from audio_analyzer.services.webhook_service import WebhookService

                webhook_svc = WebhookService()
                payload = {
                    "job_id": str(record_id),
                    "file_name": record.file_name,
                    "status": "COMPLETED",
                    "language": language,
                    "overlap_summary": overlap_summary.dict() if overlap_summary else None,
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
                await webhook_svc.send_callback_async(record.callback_url, payload)

            return True

        except Exception as ex:
            logger.error("Job execution failed for job_id=%s: %s", record_id, ex, exc_info=True)
            sanitized_msg = sanitize_error_message(ex)
            await self.repo.update_status(record_id, JobStatus.FAILED, error_message=sanitized_msg)

            if record.callback_url:
                from audio_analyzer.services.webhook_service import WebhookService

                webhook_svc = WebhookService()
                payload = {
                    "job_id": str(record_id),
                    "file_name": record.file_name,
                    "status": "FAILED",
                    "error_message": sanitized_msg,
                }
                await webhook_svc.send_callback_async(record.callback_url, payload)

            return False

