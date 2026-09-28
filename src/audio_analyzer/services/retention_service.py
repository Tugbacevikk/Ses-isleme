"""
Veri Saklama Süresi ve Temizlik Servisi (Data Retention & Cleanup Service).
AUDIO_RETENTION_HOURS: COMPLETED/FAILED ham ses dosyalarının disktan silinmesi.
RESULT_RETENTION_DAYS: Eski veritabanı kayıtlarının temizlenmesi.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from audio_analyzer.domain.interfaces import IAudioStorage, ITranscriptRepository
from audio_analyzer.domain.models import JobStatus

logger = logging.getLogger(__name__)


class RetentionService:
    """Ham ses dosyaları ve eski veritabanı kayıtları için otomatik temizleme servisi."""

    def __init__(self, storage: IAudioStorage, repository: ITranscriptRepository):
        self.storage = storage
        self.repo = repository

    async def cleanup_expired_audio_files(self, retention_hours: Optional[int] = None) -> int:
        """
        Analizi COMPLETED veya FAILED olan ve oluşturulma tarihi AUDIO_RETENTION_HOURS
        süresini geçen ham ses dosyalarını fiziksel depolamadan siler.
        Diskte yer kazandırır, gizliliği korur.
        """
        hours = retention_hours if retention_hours is not None else int(os.getenv("AUDIO_RETENTION_HOURS", "24"))
        if hours <= 0:
            return 0

        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        cleaned_count = 0

        # PENDING ve PROCESSING dışındaki (COMPLETED/FAILED) kayıtları tara
        try:
            records = await self.repo.list_records(skip=0, limit=500)
            for rec in records:
                rec_dt = rec.created_at
                if rec_dt is not None:
                    if rec_dt.tzinfo is None:
                        rec_dt = rec_dt.replace(tzinfo=timezone.utc)
                    if rec.status in (JobStatus.COMPLETED, JobStatus.FAILED) and rec_dt < threshold:
                        if rec.storage_uri:
                            try:
                                deleted = await asyncio.to_thread(self.storage.delete, rec.storage_uri)
                                if deleted:
                                    cleaned_count += 1
                                    logger.info("Zaman aşımına uğrayan ham ses dosyası silindi: %s (job_id=%s)", rec.storage_uri, rec.id)
                            except Exception as ex:
                                logger.warning("Ses dosyası silme hatası (%s): %s", rec.storage_uri, ex)
        except Exception as err:
            logger.error("Retention ses dosyası temizliği hatası: %s", err)

        return cleaned_count

    async def cleanup_old_database_records(self, retention_days: Optional[int] = None) -> int:
        """
        Oluşturulma tarihi RESULT_RETENTION_DAYS süresini aşan tüm eski veritabanı
        kayıtlarını ve ilişkili konuşmacı metinlerini kalıcı olarak siler.
        """
        days = retention_days if retention_days is not None else int(os.getenv("RESULT_RETENTION_DAYS", "30"))
        if days <= 0:
            return 0

        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        deleted_count = 0

        try:
            records = await self.repo.list_records(skip=0, limit=1000)
            for rec in records:
                rec_dt = rec.created_at
                if rec_dt is not None:
                    if rec_dt.tzinfo is None:
                        rec_dt = rec_dt.replace(tzinfo=timezone.utc)
                    if rec_dt < threshold:
                        if rec.storage_uri:
                            try:
                                await asyncio.to_thread(self.storage.delete, rec.storage_uri)
                            except Exception:
                                pass
                        deleted = await self.repo.delete_record(rec.id)
                        if deleted:
                            deleted_count += 1
                            logger.info("Zaman aşımına uğrayan eski veritabanı kaydı silindi: job_id=%s", rec.id)
        except Exception as err:
            logger.error("Retention veritabanı temizliği hatası: %s", err)

        return deleted_count
