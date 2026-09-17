import os
import tempfile

import pytest

from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter


def test_local_storage_adapter_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorageAdapter(base_dir=tmpdir)
        test_content = b"RIFF....WAVEfmt ....data...."
        filename = "test_audio.wav"

        # 1. Save file
        uri = storage.save(test_content, filename)
        assert uri.startswith("file:///")

        # 2. Get path
        local_path = storage.get_path(uri)
        assert os.path.exists(local_path)
        with open(local_path, "rb") as f:
            assert f.read() == test_content

        # 3. Delete file
        deleted = storage.delete(uri)
        assert deleted is True
        assert not os.path.exists(local_path)


def test_s3_storage_adapter_path_resolution():
    storage = S3StorageAdapter(bucket_name="test-bucket", local_cache_dir="storage/cache")
    assert storage.bucket_name == "test-bucket"

    # Non-s3 URI returns as is
    uri = "file:///tmp/test.wav"
    assert storage.get_path(uri) == uri
