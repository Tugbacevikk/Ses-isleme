import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus, TranscriptUtterance


@pytest_asyncio.fixture
async def sqlite_repo():
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
    async with session_factory() as session:
        repo = PostgresRepository(session)
        yield repo

    await engine.dispose()


@pytest.mark.asyncio
async def test_fencing_token_stale_claim_sqlite(sqlite_repo):
    repo = sqlite_repo
    record_id = uuid.uuid4()
    rec = AudioRecord(
        id=record_id,
        file_name="test_fencing.wav",
        storage_uri="disk://storage/raw/test.wav",
        file_size=1000,
        status=JobStatus.PENDING,
    )
    await repo.save_record(rec)

    # 1. Claim by Worker A
    claimed_a, rec_a, _ = await repo.claim_job_atomically(record_id, stale_seconds=1800)
    assert claimed_a is True
    token_a = rec_a.processing_started_at
    assert token_a is not None

    # Manually backdate updated_at so it looks stale for Worker B
    from audio_analyzer.adapters.repository.models import AudioRecordModel
    from sqlalchemy import update
    await repo.session.execute(
        update(AudioRecordModel)
        .where(AudioRecordModel.id == record_id)
        .values(updated_at=datetime.now(timezone.utc) - timedelta(seconds=10))
    )
    await repo.session.commit()

    # Re-claim with stale_seconds=0 to force Worker B to re-claim
    await asyncio.sleep(0.01)
    claimed_b, rec_b, _ = await repo.claim_job_atomically(record_id, stale_seconds=0)
    assert claimed_b is True
    token_b = rec_b.processing_started_at
    assert token_b is not None
    assert token_b != token_a

    # 2. Worker A attempts complete_job with stale token_a -> should return False
    utterances = [TranscriptUtterance(speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Stale text")]
    success_a = await repo.complete_job(
        record_id=record_id,
        claim_token=token_a,
        utterances=utterances,
        language="tr",
    )
    assert success_a is False

    # 3. Worker A attempts handle_job_failure with stale token_a -> should return False / not modify status
    attempts_a, is_final_a = await repo.handle_job_failure(
        record_id=record_id,
        error_message="Stale failure",
        is_transient=True,
        claim_token=token_a,
    )
    assert is_final_a is False

    # 4. Record status should still be PROCESSING with token_b
    rec_current = await repo.get_record_by_id(record_id)
    assert rec_current.status == JobStatus.PROCESSING

    # 5. Worker B completes with token_b -> should return True
    success_b = await repo.complete_job(
        record_id=record_id,
        claim_token=token_b,
        utterances=utterances,
        language="tr",
    )
    assert success_b is True
    rec_completed = await repo.get_record_by_id(record_id)
    assert rec_completed.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_fencing_token_postgres_optional():
    pg_url = os.getenv("TEST_POSTGRES_URL", os.getenv("DATABASE_URL"))
    if not pg_url or "postgresql" not in pg_url:
        pytest.skip("PostgreSQL test sunucusu mevcut değil, atlanıyor.")

    try:
        engine = create_async_engine(pg_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as ex:
        pytest.skip(f"PostgreSQL bağlantısı kurulamadı ({ex}), atlanıyor.")

    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        repo = PostgresRepository(session)
        record_id = uuid.uuid4()
        rec = AudioRecord(
            id=record_id,
            file_name="test_pg_fencing.wav",
            storage_uri="disk://storage/raw/pg.wav",
            file_size=1000,
            status=JobStatus.PENDING,
        )
        await repo.save_record(rec)

        claimed_a, rec_a, _ = await repo.claim_job_atomically(record_id, stale_seconds=1800)
        assert claimed_a is True
        token_a = rec_a.processing_started_at

        claimed_b, rec_b, _ = await repo.claim_job_atomically(record_id, stale_seconds=0)
        assert claimed_b is True
        token_b = rec_b.processing_started_at

        success_a = await repo.complete_job(
            record_id=record_id,
            claim_token=token_a,
            utterances=[],
            language="tr",
        )
        assert success_a is False

        success_b = await repo.complete_job(
            record_id=record_id,
            claim_token=token_b,
            utterances=[],
            language="tr",
        )
        assert success_b is True

    await engine.dispose()
