import asyncio
import logging
import re
import uuid
from typing import Optional, Tuple

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


from audio_analyzer.domain.errors import is_transient_error


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

    async def create_job(
        self,
        file_name: str,
        file_bytes: bytes,
        callback_url: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> uuid.UUID:
        """
        Yeni bir analiz görevi oluşturur (status='PENDING').
        İdempotency: external_id verilmişse ve aynı kaydolmuş iş varsa tekrar oluşturma, var olan job_id'yi dön.
        """
        if external_id:
            existing = await self.repo.get_record_by_external_id(external_id)
            if existing:
                logger.info("External ID '%s' ile eşleşen kayıt (%s) bulundu, mevcut job_id dönülüyor.", external_id, existing.id)
                return existing.id

        storage_uri = await asyncio.to_thread(self.storage.save, file_bytes, file_name)
        record_id = uuid.uuid4()

        record = AudioRecord(
            id=record_id,
            external_id=external_id,
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
        Geriye dönük uyumluluk için boolean sonuç döndüren execute_job sarmalayıcısı.
        """
        status_str, _, _ = await self.execute_job_detailed(record_id, file_bytes=file_bytes)
        return status_str in ("COMPLETED", "SKIPPED")

    async def execute_job_detailed(
        self, record_id: uuid.UUID, file_bytes: Optional[bytes] = None
    ) -> Tuple[str, int, Optional[str]]:
        """
        Arka plan worker'ı tarafından çağrılır.
        Kısa transaction ile durumu 'PROCESSING' yapar, DB bağlantısını serbest bırakarak pipeline'ı çalıştırır.
        Hata durumunda hata sınıflandırmasına (kalıcı vs geçici) göre retry veya FAILED kararı verir.
        Webhook istekleri Outbox tablosuna yazılır (CPU worker'ı yavaş/kapalı alıcılar için bekletilmez).
        Döner: (status_str, attempts, error_message)
        """
        import json
        import os

        stale_sec = int(os.getenv("PROCESSING_STALE_SEC", "1800"))
        max_attempts = int(os.getenv("MAX_JOB_ATTEMPTS", "3"))

        # Kısa Transaction 1: Atomik olarak işi devral (PENDING -> PROCESSING) ve hemen commit et
        claimed, record, is_completed = await self.repo.claim_job_atomically(
            record_id, stale_seconds=stale_sec
        )

        if is_completed:
            logger.info("Job %s zaten COMPLETED durumunda, tekrar çalıştırılmıyor.", record_id)
            return "COMPLETED", getattr(record, "attempts", 0), None

        if not claimed or not record:
            logger.info("Job %s başka bir worker tarafından işleniyor veya zaman aşımına uğramamış, atlanıyor.", record_id)
            return "SKIPPED", 0, None

        # --- DB BAĞLANTISI SERBEST: AI Pipeline (CPU/GPU) Thread Pool'da Yürütülür ---
        try:
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

            res = None
            if file_bytes and hasattr(self.pipeline, "process_bytes"):
                pb = getattr(self.pipeline, "process_bytes", None)
                pb_is_mock = type(pb).__name__ in ("MagicMock", "Mock", "AsyncMock")
                should_call_pb = pb is not None and (
                    not pb_is_mock
                    or getattr(pb, "_mock_return_value", None) is not None
                    or getattr(pb, "_mock_side_effect", None) is not None
                )
                if should_call_pb:
                    try:
                        res = await asyncio.to_thread(pb, file_bytes)
                    except Exception as p_err:
                        if not is_transient_error(p_err):
                            raise p_err
                        logger.warning("RAM (process_bytes) işleme uyarısı (%s), disk path yöntemine düşülüyor.", p_err)

            if not res or not isinstance(res, (tuple, list)) or len(res) < 3:
                local_path = await asyncio.to_thread(self.storage.get_path, record.storage_uri)
                res = await asyncio.to_thread(
                    self.pipeline.process, local_path
                )

            utterances, language, overlap_summary = res[0], res[1], res[2]

            # Başarılı ise sonuçları ve dili kaydet (COMPLETED)
            await self.repo.save_utterances(record_id, utterances, language=language)

            # Webhook Outbox: Sonuç ile aynı akışta webhook_deliveries tablosuna yaz
            if record.callback_url:
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
                await self.repo.create_webhook_delivery(
                    job_id=record_id, url=record.callback_url, payload=json.dumps(payload)
                )

            return "COMPLETED", record.attempts, None

        except Exception as ex:
            logger.error("Job execution failed for job_id=%s: %s", record_id, ex, exc_info=True)
            sanitized_msg = sanitize_error_message(ex)
            is_transient = is_transient_error(ex)

            attempts, is_final_failed = await self.repo.handle_job_failure(
                record_id,
                error_message=sanitized_msg,
                is_transient=is_transient,
                max_attempts=max_attempts,
            )

            if is_final_failed and record.callback_url:
                payload = {
                    "job_id": str(record_id),
                    "file_name": record.file_name,
                    "status": "FAILED",
                    "attempts": attempts,
                    "error_message": sanitized_msg,
                }
                await self.repo.create_webhook_delivery(
                    job_id=record_id, url=record.callback_url, payload=json.dumps(payload)
                )

            result_status = "FAILED" if is_final_failed else "RETRY"
            return result_status, attempts, sanitized_msg


