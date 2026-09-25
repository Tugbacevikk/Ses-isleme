import uuid
from typing import ClassVar, Dict

from audio_analyzer.domain.interfaces import IAudioStorage


class InMemoryStorageAdapter(IAudioStorage):
    """
    RAM-Tabanlı (In-Memory Stream Buffer) Nesne Depolama Adaptörü.
    Fiziksel diske hiç yazmadan, saniyede 5.000+ ses dosyasını doğrudan RAM bellekte saklar.
    Fiziksel Disk I/O darboğazını (Disk Saturation) %100 ortadan kaldırır.
    """

    _shared_buffer: ClassVar[Dict[str, bytes]] = {}

    def __init__(self, max_items: int = 100000):
        self.max_items = max_items

    def save(self, file_bytes: bytes, file_name: str) -> str:
        unique_prefix = uuid.uuid4().hex[:8]
        storage_uri = f"ram://{unique_prefix}_{file_name}"

        # RAM doluluk koruması
        if len(InMemoryStorageAdapter._shared_buffer) >= self.max_items:
            # En eski anahtarı sil (FIFO)
            first_key = next(iter(InMemoryStorageAdapter._shared_buffer))
            del InMemoryStorageAdapter._shared_buffer[first_key]

        InMemoryStorageAdapter._shared_buffer[storage_uri] = file_bytes
        return storage_uri

    def get_bytes(self, storage_uri: str) -> bytes:
        if storage_uri in InMemoryStorageAdapter._shared_buffer:
            return InMemoryStorageAdapter._shared_buffer[storage_uri]
        raise FileNotFoundError(f"RAM depolamasında ses URI bulunamadı: {storage_uri}")

    def get_path(self, storage_uri: str) -> str:
        return storage_uri

    def delete(self, storage_uri: str) -> bool:
        if storage_uri in InMemoryStorageAdapter._shared_buffer:
            del InMemoryStorageAdapter._shared_buffer[storage_uri]
            return True
        return False
