import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Analiz görevinin yaşam döngüsü durumları."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DeviceConfig(BaseModel):
    """
    Dinamik donanım ve hassasiyet (Quantization) konfigürasyonu.
    GPU varsa CUDA + float16, yoksa CPU + int8 modunu seçer.
    """

    device: str = Field(
        default_factory=lambda: "cuda" if (HAS_TORCH and torch.cuda.is_available()) else "cpu"
    )
    compute_type: str = Field(
        default_factory=lambda: "float16" if (HAS_TORCH and torch.cuda.is_available()) else "int8"
    )
    device_index: int = 0  # Çoklu GPU kartı seçimi için (0, 1, 2...)


class WordSegment(BaseModel):
    """Speech-to-Text motorundan çıkan kelime seviyesinde zaman damgalı metin birimi."""

    word: str
    start_time: float
    end_time: float
    probability: float = 1.0

    @property
    def midpoint(self) -> float:
        """Kelimenin zaman eksenindeki orta noktası."""
        return (self.start_time + self.end_time) / 2.0

    @property
    def duration(self) -> float:
        """Kelimenin telaffuz süresi (saniye)."""
        return self.end_time - self.start_time


class DiarizationSegment(BaseModel):
    """Speaker Diarization motorundan çıkan konuşmacı zaman aralığı."""

    speaker_id: str
    start_time: float
    end_time: float

    @property
    def duration(self) -> float:
        """Konuşma aralığının süresi (saniye)."""
        return self.end_time - self.start_time

    def contains_timestamp(self, ts: float) -> bool:
        """Verilen zaman damgasının bu konuşma aralığı içinde olup olmadığını kontrol eder."""
        return self.start_time <= ts <= self.end_time


class TranscriptUtterance(BaseModel):
    """Final çıktı: Konuşmacı ile eşleştirilmiş cümle/paragraf bloğu."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    speaker_id: str
    start_time: float
    end_time: float
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AudioRecord(BaseModel):
    """Ses kaydı domain varlığı."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    storage_uri: str
    file_name: str
    duration_seconds: Optional[float] = None
    sample_rate: int = 16000
    channels: int = 1
    language: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    utterances: List[TranscriptUtterance] = Field(default_factory=list)
