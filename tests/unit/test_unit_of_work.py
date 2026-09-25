import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.domain.models import AudioRecord, JobStatus


@pytest.fixture
async def in_memory_uow():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
    )
    uow = SqlAlchemyUnitOfWork(session_factory)
    yield uow
    await engine.dispose()


async def test_unit_of_work_commit_and_rollback(in_memory_uow):
    record_id = uuid.uuid4()
    record = AudioRecord(
        id=record_id,
        storage_uri="file:///tmp/uow_test.wav",
        file_name="uow_test.wav",
        status=JobStatus.PENDING,
    )

    # 1. Commit Flow via UoW Context Manager
    async with in_memory_uow as uow:
        await uow.repository.save_record(record)
        await uow.commit()

    # Verify saved
    async with in_memory_uow as uow:
        retrieved = await uow.repository.get_record_by_id(record_id)
        assert retrieved is not None
        assert retrieved.file_name == "uow_test.wav"

    # 2. Rollback Flow on Exception
    failed_id = uuid.uuid4()
    failed_record = AudioRecord(
        id=failed_id,
        storage_uri="file:///tmp/fail.wav",
        file_name="fail.wav",
        status=JobStatus.PENDING,
    )

    try:
        async with in_memory_uow as uow:
            await uow.repository.save_record(failed_record)
            raise RuntimeError("Simulated transaction error")
    except RuntimeError:
        pass

    # Verify rolled back
    async with in_memory_uow as uow:
        retrieved_failed = await uow.repository.get_record_by_id(failed_id)
        assert retrieved_failed is None

