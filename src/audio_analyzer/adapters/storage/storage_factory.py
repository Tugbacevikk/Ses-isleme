import os

from audio_analyzer.adapters.storage.in_memory_storage_adapter import (
    InMemoryStorageAdapter,
)
from audio_analyzer.adapters.storage.local_disk_storage_adapter import (
    LocalDiskStorageAdapter,
)
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter
from audio_analyzer.domain.interfaces import IAudioStorage


def get_storage_type() -> str:
    """STORAGE_TYPE ortam değişkenini küçük harf olarak döner (varsayılan 'memory')."""
    return os.getenv("STORAGE_TYPE", "memory").lower()


def get_storage_adapter() -> IAudioStorage:
    """
    STORAGE_TYPE ortam değişkenine göre uygun IAudioStorage adaptörünü döner.
    - 's3' -> S3StorageAdapter (Çoklu sunucu / bulut ortamları)
    - 'disk' -> LocalDiskStorageAdapter (Paylaşımlı volume / tek sunucu)
    - 'memory' -> InMemoryStorageAdapter (YALNIZCA tek süreçli test/CLI/BackgroundTasks ortamları)
    """
    stype = get_storage_type()
    if stype == "s3":
        return S3StorageAdapter()
    elif stype == "disk":
        return LocalDiskStorageAdapter()
    return InMemoryStorageAdapter()


def assert_storage_shared_across_processes() -> None:
    """
    Kuyruk/Worker modları (USE_REDIS_STREAM=true veya USE_REDIS_QUEUE=true) aktifken
    süreçler arası paylaşılamayan RAM depolamasının ('memory') kullanımını engeller.
    """
    use_stream = os.getenv("USE_REDIS_STREAM", "false").lower() == "true"
    use_queue = os.getenv("USE_REDIS_QUEUE", "false").lower() == "true"

    if (use_stream or use_queue) and get_storage_type() == "memory":
        raise RuntimeError("RAM depolaması süreçler arası paylaşılmaz; disk veya s3 ayarlayın")
