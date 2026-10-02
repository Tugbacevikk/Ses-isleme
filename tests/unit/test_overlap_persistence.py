import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.models import (
    AudioRecord,
    JobStatus,
    OverlapSegment,
    OverlapSummary,
)


@pytest.mark.asyncio
async def test_overlap_summary_persistence():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        repo = PostgresRepository(session, autocommit=True)

        rec_id = uuid.uuid4()
        summary = OverlapSummary(
            total_overlap_seconds=1.5,
            overlap_percentage=15.0,
            interrupt_count=2,
            overlaps=[
                OverlapSegment(speakers=["SPEAKER_00", "SPEAKER_01"], start_time=1.0, end_time=2.5, duration=1.5)
            ],
        )

        record = AudioRecord(
            id=rec_id,
            storage_uri="/path/test.wav",
            file_name="test.wav",
            status=JobStatus.PENDING,
            overlap_summary=summary,
        )

        await repo.save_record(record)

        fetched = await repo.get_record_by_id(rec_id)
        assert fetched is not None
        assert fetched.overlap_summary is not None
        assert fetched.overlap_summary.total_overlap_seconds == 1.5
        assert fetched.overlap_summary.interrupt_count == 2
        assert len(fetched.overlap_summary.overlaps) == 1
        assert fetched.overlap_summary.overlaps[0].speakers == ["SPEAKER_00", "SPEAKER_01"]

        # Test complete_job persistence
        claimed, claimed_rec, _ = await repo.claim_job_atomically(rec_id)
        assert claimed is True
        claim_token = claimed_rec.processing_started_at

        new_summary = OverlapSummary(
            total_overlap_seconds=3.0,
            overlap_percentage=30.0,
            interrupt_count=3,
            overlaps=[],
        )

        comp_ok = await repo.complete_job(
            record_id=rec_id,
            claim_token=claim_token,
            utterances=[],
            language="tr",
            overlap_summary=new_summary,
        )
        assert comp_ok is True

        fetched_completed = await repo.get_record_by_id(rec_id)
        assert fetched_completed.overlap_summary is not None
        assert fetched_completed.overlap_summary.total_overlap_seconds == 3.0
        assert fetched_completed.overlap_summary.interrupt_count == 3
