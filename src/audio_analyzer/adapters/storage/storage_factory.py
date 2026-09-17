import os
from audio_analyzer.domain.interfaces import IAudioStorage
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.adapters.storage.s3_storage_adapter import S3StorageAdapter


def get_storage_adapter() -> IAudioStorage:
    """
    STORAGE_TYPE ortam değişkenine göre uygun IAudioStorage adaptörünü döner.
    STORAGE_TYPE='s3' veya S3_BUCKET_NAME tanımlıysa S3StorageAdapter, aksi takdirde LocalStorageAdapter kullanır.
    """
    storage_type = os.getenv("STORAGE_TYPE", "local").lower()
    if storage_type == "s3":
        return S3StorageAdapter()
    return LocalStorageAdapter(base_dir="storage/raw")
