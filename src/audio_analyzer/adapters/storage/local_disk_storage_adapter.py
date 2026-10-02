import os
import re
import uuid
from pathlib import Path

from audio_analyzer.domain.interfaces import IAudioStorage


class LocalDiskStorageAdapter(IAudioStorage):
    """
    Paylaşımlı veya Yerel Disk Depolama Adaptörü (LocalDiskStorageAdapter).
    STORAGE_TYPE=disk durumunda ses dosyalarını atomik olarak diske yazar ve okur.
    Path traversal saldırılarına karşı tam korumalıdır.
    """

    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            base_dir = os.getenv("STORAGE_DIR", "storage/raw")
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, uri: str) -> Path:
        if not uri.startswith("disk://"):
            raise ValueError(f"Geçersiz disk URI şeması: {uri}")

        key = uri[len("disk://"):]
        if ".." in key or "/" in key or "\\" in key:
            raise ValueError(f"Güvenlik ihlali: Geçersiz URI anahtarı '{key}'")

        target_path = (self.base_dir / key).resolve()
        if target_path.parent != self.base_dir:
            raise ValueError(f"Dizin dışına çıkma engellendi: {target_path}")

        return target_path

    def save(self, file_bytes: bytes, file_name: str) -> str:
        # Kullanıcının dosya adı doğrudan asla yol olarak kullanılmaz
        ext = os.path.splitext(file_name)[1].lower()
        if not re.match(r"^\.[a-z0-9]{1,8}$", ext):
            ext = ".bin"

        key = f"{uuid.uuid4().hex}{ext}"
        target_path = self.base_dir / key
        tmp_path = self.base_dir / f".{key}.tmp"

        try:
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
            os.replace(tmp_path, target_path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise

        return f"disk://{key}"

    def get_path(self, uri: str) -> str:
        resolved = self._resolve(uri)
        return str(resolved)

    def get_bytes(self, uri: str) -> bytes:
        resolved = self._resolve(uri)
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"Ses dosyası bulunamadı: {uri}")
        with open(resolved, "rb") as f:
            return f.read()

    def delete(self, uri: str) -> bool:
        try:
            resolved = self._resolve(uri)
            if resolved.exists() and resolved.is_file():
                resolved.unlink()
                return True
            return False
        except (ValueError, FileNotFoundError):
            return False
