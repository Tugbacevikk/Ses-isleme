import os
import uuid
from pathlib import Path
from audio_analyzer.domain.interfaces import IAudioStorage


class LocalStorageAdapter(IAudioStorage):
    """
    Yerel Dosya Sistemi (Local Disk) Nesne Depolama Adaptörü.
    Geliştirme ve test ortamında ses dosyalarını diskteki `storage/` klasöründe saklar.
    """

    def __init__(self, base_dir: str = "storage/raw"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file_bytes: bytes, file_name: str) -> str:
        unique_prefix = uuid.uuid4().hex[:8]
        safe_filename = f"{unique_prefix}_{file_name}"
        file_path = self.base_dir / safe_filename
        
        with open(file_path, "wb") as f:
            f.write(file_bytes)
            
        return f"file:///{file_path.absolute().as_posix()}"

    def get_path(self, storage_uri: str) -> str:
        if storage_uri.startswith("file:///"):
            return storage_uri.replace("file:///", "")
        return storage_uri

    def delete(self, storage_uri: str) -> bool:
        path_str = self.get_path(storage_uri)
        file_path = Path(path_str)
        if file_path.exists():
            file_path.unlink()
            return True
        return False
