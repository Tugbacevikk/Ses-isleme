import os

from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter
from audio_analyzer.domain.interfaces import IAudioStorage


def get_storage_adapter() -> IAudioStorage:
    """
    STORAGE_TYPE ortam değişkenine göre uygun IAudioStorage adaptörünü döner.
    STORAGE_TYPE='s3' -> S3StorageAdapter
    Varsayılan -> InMemoryStorageAdapter (%100 RAM 0-Disk I/O)
    """
    storage_type = os.getenv("STORAGE_TYPE", "memory").lower()

    if storage_type == "s3":
        return S3StorageAdapter()
    return InMemoryStorageAdapter()

