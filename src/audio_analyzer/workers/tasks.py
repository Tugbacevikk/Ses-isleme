import os
import uuid
from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.services.job_service import JobService
from audio_analyzer.workers.celery_app import celery_app

# Database URL (Default: SQLite for dev/local, PostgreSQL for prod)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")


@celery_app.task(name="process_audio_task", bind=True, max_retries=3)
def process_audio_task(self, record_id_str: str) -> Dict[str, Any]:
    """
    Arka planda Celery Worker tarafından yürütülen ses analiz görevi (Unit-of-Work ile).

    1. UnitOfWork ile transaction sınırlarını yönetir.
    2. JobService üzerinden ses dosyasını analiz eder.
    3. Sonuç durumunu döner.
    """
    record_id = uuid.UUID(record_id_str)
    engine = create_engine(DATABASE_URL, echo=False)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    uow = SqlAlchemyUnitOfWork(session_factory=session_factory)

    with uow:
        # 1. Depo ve Sıcak Yüklenmiş (Warm-loaded) Singleton AI Pipeline
        storage = LocalStorageAdapter(base_dir="storage/raw")

        from audio_analyzer.services.pipeline_factory import get_shared_pipeline

        pipeline = get_shared_pipeline()

        job_service = JobService(
            storage=storage,
            repository=uow.repository,
            pipeline=pipeline,
        )

        # 3. Analiz Görevinin Yürütülmesi
        success = job_service.execute_job(record_id)

        if success:
            return {"record_id": record_id_str, "status": "COMPLETED"}
        else:
            return {"record_id": record_id_str, "status": "FAILED"}
