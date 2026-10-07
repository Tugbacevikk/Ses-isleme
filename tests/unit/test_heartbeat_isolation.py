import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.job_service import JobService


@pytest.mark.asyncio
async def test_heartbeat_loop_uses_session_factory_not_main_repo():
    mock_storage = MagicMock()
    mock_main_repo = AsyncMock()

    record_id = uuid.uuid4()
    mock_record = AudioRecord(
        id=record_id,
        storage_uri="disk://test.wav",
        file_name="test.wav",
        status=JobStatus.PENDING,
    )

    mock_main_repo.claim_job_atomically.return_value = (True, mock_record, False)
    mock_main_repo.complete_job.return_value = True

    mock_hb_session = AsyncMock()
    mock_session_factory = MagicMock()
    # Mock context manager for session_factory
    mock_session_factory.return_value.__aenter__.return_value = mock_hb_session

    mock_pipeline = MagicMock()
    mock_pipeline.process_bytes.return_value = ([], "tr", None)

    job_service = JobService(
        storage=mock_storage,
        repository=mock_main_repo,
        pipeline=mock_pipeline,
        session_factory=mock_session_factory,
    )

    import time

    real_sleep = asyncio.sleep

    async def fast_sleep(sec):
        if sec == 60.0:
            await real_sleep(0.001)
        else:
            await real_sleep(sec)

    def slow_process_bytes(file_bytes):
        time.sleep(0.05)
        return ([], "tr", None)

    mock_pipeline.process_bytes.side_effect = slow_process_bytes

    with patch("audio_analyzer.services.job_service.asyncio.sleep", fast_sleep):
        with patch("audio_analyzer.adapters.repository.postgres_repository.PostgresRepository") as mock_repo_cls:
            mock_repo_inst = AsyncMock()
            mock_repo_cls.return_value = mock_repo_inst
            await job_service.execute_job_detailed(record_id, file_bytes=b"dummy")

    # Verify session_factory was called for heartbeat
    mock_session_factory.assert_called()
    # Verify main repo touch_processing was NOT called
    mock_main_repo.touch_processing.assert_not_called()
