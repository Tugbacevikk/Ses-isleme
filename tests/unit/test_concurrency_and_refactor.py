import asyncio
import uuid
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus, TranscriptUtterance
from audio_analyzer.services.job_service import JobService
from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.workers.sweeper import SweeperService
from audio_analyzer.workers.stream_worker import RedisStreamWorker

@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def repo(async_engine):
    session_factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield PostgresRepository(session=session, autocommit=True)

@pytest.mark.asyncio
async def test_complete_job_twice_does_not_duplicate_utterances(repo):
    record_id = uuid.uuid4()
    record = AudioRecord(
        id=record_id,
        file_name="test.wav",
        storage_uri="memory://test.wav",
        status=JobStatus.PENDING,
    )
    await repo.save_record(record)
    
    claimed, claimed_record, _ = await repo.claim_job_atomically(record_id)
    assert claimed is True
    claim_token = claimed_record.processing_started_at
    assert claim_token is not None
    
    utterances = [
        TranscriptUtterance(id=uuid.uuid4(), speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Merhaba")
    ]
    
    res1 = await repo.complete_job(
        record_id=record_id,
        claim_token=claim_token,
        utterances=utterances,
        language="tr"
    )
    assert res1 is True
    
    rec_after_1 = await repo.get_record_by_id(record_id)
    assert len(rec_after_1.utterances) == 1
    
    res2 = await repo.complete_job(
        record_id=record_id,
        claim_token=claim_token,
        utterances=utterances,
        language="tr"
    )
    assert res2 is True
    rec_after_2 = await repo.get_record_by_id(record_id)
    assert len(rec_after_2.utterances) == 1

@pytest.mark.asyncio
async def test_complete_job_with_stale_claim_token_fails(repo):
    record_id = uuid.uuid4()
    record = AudioRecord(
        id=record_id,
        file_name="test.wav",
        storage_uri="memory://test.wav",
        status=JobStatus.PENDING,
    )
    await repo.save_record(record)
    
    claimed, claimed_record, _ = await repo.claim_job_atomically(record_id)
    
    stale_token = datetime(2020, 1, 1, tzinfo=timezone.utc)
    utterances = [
        TranscriptUtterance(id=uuid.uuid4(), speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Eski token metni")
    ]
    
    res = await repo.complete_job(
        record_id=record_id,
        claim_token=stale_token,
        utterances=utterances,
        language="tr"
    )
    assert res is False, "Eski/yanlış claim_token ile complete_job False dönmeli!"

@pytest.mark.asyncio
async def test_concurrent_execute_job_utterances_saved_once(async_engine):
    session_factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    
    storage = InMemoryStorageAdapter()
    storage_uri = storage.save(b"fake wav bytes", "test.wav")
    
    async with session_factory() as session1, session_factory() as session2:
        repo1 = PostgresRepository(session=session1, autocommit=True)
        repo2 = PostgresRepository(session=session2, autocommit=True)
        
        record_id = uuid.uuid4()
        record = AudioRecord(
            id=record_id,
            file_name="test.wav",
            storage_uri=storage_uri,
            status=JobStatus.PENDING,
        )
        await repo1.save_record(record)
        
        pipeline_mock = MagicMock()
        mock_u = [TranscriptUtterance(id=uuid.uuid4(), speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Test")]
        pipeline_mock.process.return_value = (mock_u, "tr", None)
        pipeline_mock.process_bytes.return_value = (mock_u, "tr", None)
        
        svc1 = JobService(storage=storage, repository=repo1, pipeline=pipeline_mock)
        svc2 = JobService(storage=storage, repository=repo2, pipeline=pipeline_mock)
        
        res1, res2 = await asyncio.gather(
            svc1.execute_job(record_id, file_bytes=b"fake wav bytes"),
            svc2.execute_job(record_id, file_bytes=b"fake wav bytes"),
        )
        
        rec = await repo1.get_record_by_id(record_id)
        assert len(rec.utterances) == 1, f"Utterance'lar yalnızca 1 kez kaydedilmeli, ancak {len(rec.utterances)} adet kaydoldu!"

@pytest.mark.asyncio
async def test_sweeper_skips_pending_when_lag_greater_than_zero(repo):
    record_id = uuid.uuid4()
    record = AudioRecord(
        id=record_id,
        file_name="test.wav",
        storage_uri="memory://test.wav",
        status=JobStatus.PENDING,
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    await repo.save_record(record)
    
    adapter_mock = MagicMock()
    adapter_mock.get_consumer_group_lag = AsyncMock(return_value=5)  # lag = 5 > 0
    adapter_mock.publish_job = AsyncMock()
    
    sweeper = SweeperService(adapter=adapter_mock)
    
    class DummyUOW:
        def __init__(self, repository):
            self.repository = repository
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
            
    with patch("audio_analyzer.workers.sweeper.SqlAlchemyUnitOfWork", return_value=DummyUOW(repo)):
        await sweeper.run_single_sweep()
        
    adapter_mock.publish_job.assert_not_called()

@pytest.mark.asyncio
async def test_stream_worker_poison_pill_acked_and_sent_to_dlq():
    adapter_mock = MagicMock()
    adapter_mock.get_pending_delivery_count = AsyncMock(return_value=5)  # delivery_count 5 > MAX (3)
    adapter_mock.publish_to_dlq = AsyncMock()
    adapter_mock.ack_message = AsyncMock()
    adapter_mock.claim_message_heartbeat = AsyncMock()
    
    worker = RedisStreamWorker(adapter=adapter_mock)
    
    fake_repo = MagicMock()
    fake_repo.claim_job_atomically = AsyncMock(side_effect=RuntimeError("Simulated pipeline crash"))
    fake_repo.handle_job_failure = AsyncMock(return_value=(5, True))
    
    class DummyUOW:
        def __init__(self, repository):
            self.repository = repository
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("audio_analyzer.workers.stream_worker.SqlAlchemyUnitOfWork", return_value=DummyUOW(fake_repo)):
        success = await worker.process_single_message("msg-123", {"job_id": str(uuid.uuid4())})
        assert success is False
        
    adapter_mock.publish_to_dlq.assert_called_once()
    adapter_mock.ack_message.assert_called()
