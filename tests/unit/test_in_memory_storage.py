import uuid
from unittest.mock import MagicMock

import pytest

from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter
from audio_analyzer.adapters.storage.storage_factory import get_storage_adapter
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.models import JobStatus
from audio_analyzer.services.job_service import JobService


@pytest.mark.unit
def test_in_memory_storage_adapter_crud():
    adapter = InMemoryStorageAdapter()
    file_bytes = b"RIFFfakebytes123456789"
    file_name = "test_ram_audio.wav"

    # 1. Save (RAM'e Kaydet)
    uri = adapter.save(file_bytes, file_name)
    assert uri.startswith("ram://")

    # 2. Get Bytes (Fiziksel diske hiç yazmadan RAM'den oku)
    retrieved_bytes = adapter.get_bytes(uri)
    assert retrieved_bytes == file_bytes

    # 3. Get Path (ram:// URI formatı)
    path = adapter.get_path(uri)
    assert path == uri

    # 4. Delete (RAM'den Sil)
    deleted = adapter.delete(uri)
    assert deleted is True

    with pytest.raises(FileNotFoundError):
        adapter.get_bytes(uri)


@pytest.mark.unit
def test_in_memory_storage_adapter_fifo_limit():
    InMemoryStorageAdapter._shared_buffer.clear()
    adapter = InMemoryStorageAdapter(max_items=2)
    uri1 = adapter.save(b"bytes1", "file1.wav")
    uri2 = adapter.save(b"bytes2", "file2.wav")
    uri3 = adapter.save(b"bytes3", "file3.wav")  # Limiti asar, uri1 FIFO ile silinmeli


    assert adapter.get_bytes(uri2) == b"bytes2"
    assert adapter.get_bytes(uri3) == b"bytes3"
    with pytest.raises(FileNotFoundError):
        adapter.get_bytes(uri1)


@pytest.mark.unit
def test_storage_factory_ram_selection(monkeypatch):
    monkeypatch.setenv("STORAGE_TYPE", "memory")
    adapter = get_storage_adapter()
    assert isinstance(adapter, InMemoryStorageAdapter)

    monkeypatch.setenv("STORAGE_TYPE", "local")
    monkeypatch.setenv("USE_RAM_STORAGE", "true")
    ram_adapter = get_storage_adapter()
    assert isinstance(ram_adapter, InMemoryStorageAdapter)


@pytest.mark.unit
def test_s3_storage_adapter_get_bytes(monkeypatch):
    mock_boto3_client = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = b"S3_RAM_STREAM_BYTES"
    mock_boto3_client.get_object.return_value = {"Body": mock_body}

    s3_adapter = S3StorageAdapter(bucket_name="test-bucket")
    monkeypatch.setattr(s3_adapter, "_get_client", lambda: mock_boto3_client)

    uri = "s3://test-bucket/raw_audio/call.wav"
    bytes_out = s3_adapter.get_bytes(uri)

    assert bytes_out == b"S3_RAM_STREAM_BYTES"
    mock_boto3_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="raw_audio/call.wav")


@pytest.mark.unit
async def test_job_service_with_in_memory_storage_e2e(in_memory_db):
    storage = InMemoryStorageAdapter()
    repository = PostgresRepository(session=in_memory_db)

    mock_pipeline = MagicMock()
    mock_pipeline.process_bytes.return_value = ([], "tr", None)

    job_service = JobService(storage=storage, repository=repository, pipeline=mock_pipeline)

    # 1. Job oluştur (RAM'e kaydolur)
    file_bytes = b"RIFFtestbytesforramstream"
    job_id = await job_service.create_job("call.wav", file_bytes)

    record_pending = await repository.get_record_by_id(job_id)
    assert record_pending is not None
    assert record_pending.storage_uri.startswith("ram://")

    # 2. Worker execute_job çağırır (diske HİÇ dokunmadan RAM baytları ile process_bytes çalışır)
    success = await job_service.execute_job(job_id)
    assert success is True
    assert mock_pipeline.process_bytes.called
    assert mock_pipeline.process_bytes.call_args[0][0] == file_bytes

    record_completed = await repository.get_record_by_id(job_id)
    assert record_completed.status == JobStatus.COMPLETED
