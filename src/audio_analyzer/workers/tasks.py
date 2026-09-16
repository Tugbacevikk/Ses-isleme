import os
import uuid
from typing import Dict, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.workers.celery_app import celery_app
from audio_analyzer.domain.models import DeviceConfig
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.stt.faster_whisper_adapter import FasterWhisperAdapter
from audio_analyzer.adapters.diarization.pyannote_adapter import PyAnnoteAdapter
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.services.job_service import JobService

# Database URL (Default: SQLite for dev/local, PostgreSQL for prod)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")


def get_db_session():
    """Veritabanı oturumu oluşturan yardımcı fonksiyon."""
    engine = create_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


@celery_app.task(name="process_audio_task", bind=True, max_retries=3)
def process_audio_task(self, record_id_str: str) -> Dict[str, Any]:
    """
    Arka planda Celery Worker tarafından yürütülen ses analiz görevi.
    
    1. Veritabanı ve Donanım Adaptörlerini (DeviceConfig) ayağa kaldırır.
    2. JobService üzerinden ses dosyasını analiz eder.
    3. Sonuç durumunu döner.
    """
    record_id = uuid.UUID(record_id_str)
    session = get_db_session()

    try:
        # 1. Depo ve Sıcak Yüklenmiş (Warm-loaded) Singleton AI Pipeline
        storage = LocalStorageAdapter(base_dir="storage/raw")
        repository = PostgresRepository(session=session)
        
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline
        pipeline = get_shared_pipeline()


        job_service = JobService(
            storage=storage,
            repository=repository,
            pipeline=pipeline,
        )

        # 3. Analiz Görevinin Yürütülmesi
        success = job_service.execute_job(record_id)
        
        if success:
            return {"record_id": record_id_str, "status": "COMPLETED"}
        else:
            return {"record_id": record_id_str, "status": "FAILED"}

    except Exception as exc:
        # Hata durumunda yeniden deneme (retry) veya hata loglama
        session.rollback()
        raise exc
    finally:
        session.close()
