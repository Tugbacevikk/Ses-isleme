import os

from audio_analyzer.adapters.storage.in_memory_storage_adapter import InMemoryStorageAdapter
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter
from audio_analyzer.domain.interfaces import IAudioStorage


def get_storage_adapter() -> IAudioStorage:
    """
    STORAGE_TYPE veya USE_RAM_STORAGE ortam değişkenlerine göre uygun IAudioStorage adaptörünü döner.
    STORAGE_TYPE='memory' / 'ram' veya USE_RAM_STORAGE='true' -> InMemoryStorageAdapter (%100 RAM 0-Disk I/O)
    STORAGE_TYPE='s3' -> S3StorageAdapter
    Aksi takdirde -> LocalStorageAdapter
    """
    storage_type = os.getenv("STORAGE_TYPE", "local").lower()
    use_ram = os.getenv("USE_RAM_STORAGE", "false").lower() == "true"

    if storage_type in ("memory", "ram") or use_ram:
        return InMemoryStorageAdapter()
    elif storage_type == "s3":
        return S3StorageAdapter()
    return LocalStorageAdapter(base_dir="storage/raw")
