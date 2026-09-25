import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.job_service import JobService, sanitize_error_message


def test_sanitize_error_message_removes_file_paths():
    ex = FileNotFoundError("No such file: C:\\Users\\ADIL CEVIK\\Desktop\\sesAnalizi\\storage\\raw\\test.wav")
    sanitized = sanitize_error_message(ex)

    assert "C:\\Users\\" not in sanitized
    assert "[FILE_PATH]" in sanitized
    assert "FileNotFoundError" in sanitized


async def test_execute_job_failure_does_not_leak_traceback(in_memory_db):
    storage = InMemoryStorageAdapter()
    repository = PostgresRepository(session=in_memory_db)

    # Pipeline that raises an error
    mock_pipeline = MagicMock()
    mock_pipeline.process.side_effect = RuntimeError("Internal model failure in C:\\Secret\\Path\\model.py")

    job_service = JobService(storage=storage, repository=repository, pipeline=mock_pipeline)

    record_id = await job_service.create_job("test_audio.wav", b"RIFFfakebytes")
    success = await job_service.execute_job(record_id)

    assert success is False

    record = await repository.get_record_by_id(record_id)
    assert record is not None
    assert record.status == JobStatus.FAILED
    assert record.error_message is not None

    # Verify no raw traceback or local path is present in error_message
    assert "Traceback (most recent call last)" not in record.error_message
    assert "C:\\Secret\\Path" not in record.error_message
    assert "RuntimeError" in record.error_message


async def test_execute_job_triggers_webhook_callback(in_memory_db, monkeypatch):
    storage = InMemoryStorageAdapter()
    repository = PostgresRepository(session=in_memory_db)

    mock_pipeline = MagicMock()
    mock_pipeline.process.return_value = ([], "tr", None)

    mock_send_callback = AsyncMock(return_value=True)
    monkeypatch.setattr("audio_analyzer.services.webhook_service.WebhookService.send_callback_async", mock_send_callback)

    job_service = JobService(storage=storage, repository=repository, pipeline=mock_pipeline)

    record_id = await job_service.create_job("test_audio.wav", b"RIFFfakebytes", callback_url="https://example.com/webhook")
    success = await job_service.execute_job(record_id)

    assert success is True
    assert mock_send_callback.called
    assert mock_send_callback.call_args[0][0] == "https://example.com/webhook"
    assert mock_send_callback.call_args[0][1]["status"] == "COMPLETED"



