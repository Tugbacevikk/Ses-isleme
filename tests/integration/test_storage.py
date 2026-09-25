import os
import tempfile

import pytest

from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter


def test_in_memory_storage_adapter_lifecycle():
    storage = InMemoryStorageAdapter()
    test_content = b"RIFF....WAVEfmt ....data...."
    filename = "test_audio.wav"

    # 1. Save file
    uri = storage.save(test_content, filename)
    assert uri.startswith("ram://")

    # 2. Get bytes
    retrieved_bytes = storage.get_bytes(uri)
    assert retrieved_bytes == test_content

    # 3. Delete file
    deleted = storage.delete(uri)
    assert deleted is True
    with pytest.raises(FileNotFoundError):
        storage.get_bytes(uri)




def test_s3_storage_adapter_path_resolution():
    storage = S3StorageAdapter(bucket_name="test-bucket", local_cache_dir="storage/cache")
    assert storage.bucket_name == "test-bucket"

    # Non-s3 URI returns as is
    uri = "file:///tmp/test.wav"
    assert storage.get_path(uri) == uri
