import asyncio
import os
import uuid
from typing import Any, Dict

from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.api.dependencies import create_async_db_engine
from audio_analyzer.services.job_service import JobService
from audio_analyzer.workers.celery_app import celery_app

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")


async def _run_async_process_task(record_id: uuid.UUID) -> bool:
    engine = create_async_db_engine(DATABASE_URL)
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
    )
    uow = SqlAlchemyUnitOfWork(session_factory=session_factory)

    async with uow:
        storage = LocalStorageAdapter(base_dir="storage/raw")
        from audio_analyzer.services.pipeline_factory import get_shared_pipeline

        pipeline = get_shared_pipeline()

        job_service = JobService(
            storage=storage,
            repository=uow.repository,
            pipeline=pipeline,
        )

        return await job_service.execute_job(record_id)


@celery_app.task(name="process_audio_task", bind=True, max_retries=3)
def process_audio_task(self, record_id_str: str) -> Dict[str, Any]:
    """
    Arka planda Celery Worker tarafından yürütülen ses analiz görevi (Async Unit-of-Work ile).

    1. UnitOfWork ile transaction sınırlarını yönetir.
    2. JobService üzerinden ses dosyasını analiz eder.
    3. Sonuç durumunu döner.
    """
    record_id = uuid.UUID(record_id_str)
    success = asyncio.run(_run_async_process_task(record_id))

    if success:
        return {"record_id": record_id_str, "status": "COMPLETED"}
    else:
        return {"record_id": record_id_str, "status": "FAILED"}

