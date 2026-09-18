import uuid
from unittest.mock import MagicMock

import pytest

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.job_service import JobService, sanitize_error_message


def test_sanitize_error_message_removes_file_paths():
    ex = FileNotFoundError("No such file: C:\\Users\\ADIL CEVIK\\Desktop\\sesAnalizi\\storage\\raw\\test.wav")
    sanitized = sanitize_error_message(ex)

    assert "C:\\Users\\" not in sanitized
    assert "[FILE_PATH]" in sanitized
    assert "FileNotFoundError" in sanitized


def test_execute_job_failure_does_not_leak_traceback(tmp_path, in_memory_db):
    storage = LocalStorageAdapter(base_dir=str(tmp_path / "storage"))
    repository = PostgresRepository(session=in_memory_db)

    # Pipeline that raises an error
    mock_pipeline = MagicMock()
    mock_pipeline.process.side_effect = RuntimeError("Internal model failure in C:\\Secret\\Path\\model.py")

    job_service = JobService(storage=storage, repository=repository, pipeline=mock_pipeline)

    record_id = job_service.create_job("test_audio.wav", b"RIFFfakebytes")
    success = job_service.execute_job(record_id)

    assert success is False

    record = repository.get_record_by_id(record_id)
    assert record is not None
    assert record.status == JobStatus.FAILED
    assert record.error_message is not None

    # Verify no raw traceback or local path is present in error_message
    assert "Traceback (most recent call last)" not in record.error_message
    assert "C:\\Secret\\Path" not in record.error_message
    assert "RuntimeError" in record.error_message
