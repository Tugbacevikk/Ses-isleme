"""
Veri Saklama Süresi ve Temizlik Servisi (Data Retention & Cleanup Service).
AUDIO_RETENTION_HOURS: COMPLETED/FAILED ham ses dosyalarının disktan silinmesi.
RESULT_RETENTION_DAYS: Eski veritabanı kayıtlarının temizlenmesi.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from audio_analyzer.domain.interfaces import IAudioStorage, ITranscriptRepository
from audio_analyzer.domain.models import JobStatus

logger = logging.getLogger(__name__)


class RetentionService:
    """Ham ses dosyaları ve eski veritabanı kayıtları için otomatik temizleme servisi."""

    def __init__(self, storage: IAudioStorage, repository: ITranscriptRepository):
        self.storage = storage
        self.repo = repository

    async def cleanup_expired_audio_files(self, retention_hours: int | None = None) -> int:
        """
        Analizi COMPLETED veya FAILED olan ve oluşturulma tarihi AUDIO_RETENTION_HOURS
        süresini geçen ham ses dosyalarını fiziksel depolamadan siler.
        Diskte yer kazandırır, gizliliği korur.
        """
        from audio_analyzer.config import get_settings
        settings = get_settings()
        hours = retention_hours if retention_hours is not None else settings.audio_retention_hours
        if hours <= 0:
            return 0

        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        cleaned_count = 0
        batch_size = 100

        try:
            while True:
                expired_records = await self.repo.get_expired_records(
                    before=threshold,
                    statuses=[JobStatus.COMPLETED, JobStatus.FAILED],
                    limit=batch_size,
                )
                if not expired_records:
                    break

                for rec in expired_records:
                    if rec.storage_uri:
                        try:
                            deleted = await asyncio.to_thread(self.storage.delete, rec.storage_uri)
                            if deleted:
                                cleaned_count += 1
                                logger.info("Zaman aşımına uğrayan ham ses dosyası silindi: %s (job_id=%s)", rec.storage_uri, rec.id)
                        except Exception as ex:
                            logger.warning("Ses dosyası silme hatası (%s): %s", rec.storage_uri, ex)

                if len(expired_records) < batch_size:
                    break
        except Exception as err:
            logger.error("Retention ses dosyası temizliği hatası: %s", err)

        return cleaned_count

    async def cleanup_old_database_records(self, retention_days: int | None = None) -> int:
        """
        Oluşturulma tarihi RESULT_RETENTION_DAYS süresini aşan tüm eski veritabanı
        kayıtlarını ve ilişkili konuşmacı metinlerini kalıcı olarak siler.
        """
        from audio_analyzer.config import get_settings
        settings = get_settings()
        days = retention_days if retention_days is not None else settings.result_retention_days
        if days <= 0:
            return 0

        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        deleted_count = 0
        batch_size = 100

        try:
            while True:
                expired_records = await self.repo.get_expired_records(
                    before=threshold,
                    limit=batch_size,
                )
                if not expired_records:
                    break

                for rec in expired_records:
                    if rec.storage_uri:
                        try:
                            await asyncio.to_thread(self.storage.delete, rec.storage_uri)
                        except Exception:
                            pass
                    deleted = await self.repo.delete_record(rec.id)
                    if deleted:
                        deleted_count += 1
                        logger.info("Zaman aşımına uğrayan eski veritabanı kaydı silindi: job_id=%s", rec.id)

                if len(expired_records) < batch_size:
                    break
        except Exception as err:
            logger.error("Retention veritabanı temizliği hatası: %s", err)

        return deleted_count
