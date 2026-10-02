import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from audio_analyzer.adapters.messaging.redis_stream_adapter import RedisStreamAdapter
from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.errors import PermanentJobError, TransientJobError
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.job_service import JobService
from audio_analyzer.workers.sweeper import SweeperService


@pytest.fixture
async def async_test_db():
    db_file = os.path.join(tempfile.gettempdir(), f"test_sweeper_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    yield session_factory, engine

    await engine.dispose()
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
    except Exception:
        pass


@pytest.mark.unit
async def test_permanent_error_immediate_dlq(async_test_db, monkeypatch):
    """Kalıcı hata alan işin hemen FAILED olduğunu ve DLQ akışına aktarıldığını doğrular."""
    session_factory, _ = async_test_db
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "3")

    fake_server = fakeredis.aioredis.FakeServer()
    fake_redis = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    stream_adapter = RedisStreamAdapter(redis_client=fake_redis)
    await stream_adapter.create_consumer_group()

    record_id = uuid.uuid4()
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        record = AudioRecord(
            id=record_id,
            storage_uri="ram://corrupt.wav",
            file_name="corrupt.wav",
            status=JobStatus.PENDING,
        )
        await repo.save_record(record)

    # Kalıcı hata veren mock pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.process_bytes.side_effect = PermanentJobError("Bozuk ses dosyası başlığı")
    mock_storage = MagicMock()
    mock_storage.get_bytes.return_value = b"corrupt_bytes"

    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        job_svc = JobService(storage=mock_storage, repository=repo, pipeline=mock_pipeline)
        status_str, attempts, err_msg = await job_svc.execute_job_detailed(record_id)

    assert status_str == "FAILED"
    assert attempts == 1
    assert "Bozuk ses dosyası" in err_msg

    # DB kaydı FAILED olmalı
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        rec = await repo.get_record_by_id(record_id)
        assert rec.status == JobStatus.FAILED
        assert rec.attempts == 1


@pytest.mark.unit
async def test_transient_error_retry_and_dlq_on_max_attempts(async_test_db, monkeypatch):
    """Geçici hata alan işin attempts artarak yeniden denendiğini, 3. denemede DLQ'ya aktarıldığını doğrular."""
    session_factory, _ = async_test_db
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "3")

    record_id = uuid.uuid4()
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        record = AudioRecord(
            id=record_id,
            storage_uri="ram://transient.wav",
            file_name="transient.wav",
            status=JobStatus.PENDING,
        )
        await repo.save_record(record)

    mock_pipeline = MagicMock()
    mock_pipeline.process_bytes.side_effect = TransientJobError("Geçici bellek / network hatası")
    mock_pipeline.process.side_effect = TransientJobError("Geçici bellek / network hatası")
    mock_storage = MagicMock()
    mock_storage.get_bytes.return_value = b"audio_bytes"

    # 1. Deneme -> RETRY
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        job_svc = JobService(storage=mock_storage, repository=repo, pipeline=mock_pipeline)
        s1, a1, _ = await job_svc.execute_job_detailed(record_id)
    assert s1 == "RETRY"
    assert a1 == 1

    # DB kaydı PENDING durumuna dönmeli
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        r1 = await repo.get_record_by_id(record_id)
        assert r1.status == JobStatus.PENDING
        assert r1.attempts == 1

    # 2. Deneme -> RETRY
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        job_svc = JobService(storage=mock_storage, repository=repo, pipeline=mock_pipeline)
        s2, a2, _ = await job_svc.execute_job_detailed(record_id)
    assert s2 == "RETRY"
    assert a2 == 2

    # 3. Deneme (Maks Deneme Aşıldı) -> FAILED
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        job_svc = JobService(storage=mock_storage, repository=repo, pipeline=mock_pipeline)
        s3, a3, _ = await job_svc.execute_job_detailed(record_id)
    assert s3 == "FAILED"
    assert a3 == 3

    # DB kaydı FAILED olmalı
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        r3 = await repo.get_record_by_id(record_id)
        assert r3.status == JobStatus.FAILED
        assert r3.attempts == 3


@pytest.mark.unit
async def test_sweeper_stale_pending_and_processing(async_test_db, monkeypatch):
    """Sweeper'ın zaman aşımına uğramış PENDING ve PROCESSING kayıtlarını başarıyla toparladığını doğrular."""
    session_factory, _ = async_test_db
    monkeypatch.setenv("PENDING_STALE_SEC", "0")
    monkeypatch.setenv("PROCESSING_STALE_SEC", "0")
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "3")

    fake_server = fakeredis.aioredis.FakeServer()
    fake_redis = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    stream_adapter = RedisStreamAdapter(redis_client=fake_redis)

    pending_id = uuid.uuid4()
    processing_id = uuid.uuid4()
    stale_failed_id = uuid.uuid4()

    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        # 1. Bekleyen yetim PENDING kaydı
        await repo.save_record(
            AudioRecord(id=pending_id, storage_uri="ram://p.wav", file_name="p.wav", status=JobStatus.PENDING)
        )
        # 2. Yeniden denenebilir askıda PROCESSING kaydı (attempts=1)
        r_proc = AudioRecord(id=processing_id, storage_uri="ram://pr.wav", file_name="pr.wav", status=JobStatus.PROCESSING, attempts=1)
        await repo.save_record(r_proc)

        # 3. Maks limiti aşmış askıda PROCESSING kaydı (attempts=3)
        r_fail = AudioRecord(id=stale_failed_id, storage_uri="ram://f.wav", file_name="f.wav", status=JobStatus.PROCESSING, attempts=3)
        await repo.save_record(r_fail)

    sweeper = SweeperService(adapter=stream_adapter)
    with patch("audio_analyzer.workers.sweeper.AsyncSessionLocal", session_factory):
        await sweeper.run_single_sweep()

    # Kontroller
    async with session_factory() as session:
        repo = PostgresRepository(session=session)
        r_proc_after = await repo.get_record_by_id(processing_id)
        assert r_proc_after.status == JobStatus.PENDING

        r_fail_after = await repo.get_record_by_id(stale_failed_id)
        assert r_fail_after.status == JobStatus.FAILED

    # DLQ kontrolü
    client = stream_adapter.get_client()
    dlq_msgs = await client.xrange("audio_analysis_dlq")
    assert len(dlq_msgs) >= 1
    assert str(stale_failed_id) in str(dlq_msgs[0][1])


@pytest.mark.unit
async def test_api_xadd_failure_returns_503(monkeypatch):
    """API'de Redis Stream XADD başarısız olduğunda 503 Service Unavailable döndüğünü doğrular."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from audio_analyzer.api.dependencies import get_repository
    from audio_analyzer.api.routers.jobs import router

    mock_repo = AsyncMock()
    mock_repo.save_record.return_value = AudioRecord(id=uuid.uuid4(), storage_uri="ram://test.wav", file_name="test.wav")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: mock_repo

    client = TestClient(app)

    monkeypatch.setenv("USE_REDIS_STREAM", "true")

    with patch("audio_analyzer.adapters.messaging.redis_stream_adapter.RedisStreamAdapter.publish_job") as mock_pub:
        mock_pub.side_effect = Exception("Redis bağlantı hatası")

        response = client.post(
            "/api/v1/analyze",
            files={"file": ("test.wav", b"RIFF____WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00", "audio/wav")},
        )

        assert response.status_code == 503
        assert response.headers.get("retry-after") == "5"
        assert "Mesaj kuyruğu servisi geçici olarak yanıt vermiyor" in response.json()["detail"]
