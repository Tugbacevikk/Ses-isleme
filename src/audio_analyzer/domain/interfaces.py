import uuid
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from audio_analyzer.domain.models import (
    AudioRecord,
    TranscriptUtterance,
    WordSegment,
    DiarizationSegment,
    JobStatus,
)


class IAudioStorage(ABC):
    """Nesne Depolama (Object Storage / Local FS) Soyut Arayüzü."""

    @abstractmethod
    def save(self, file_bytes: bytes, file_name: str) -> str:
        """Ses dosyasını depolar ve benzersiz bir storage_uri döner."""
        pass

    @abstractmethod
    def get_path(self, storage_uri: str) -> str:
        """storage_uri'den yerel erişilebilir dosya yolunu döner."""
        pass

    @abstractmethod
    def delete(self, storage_uri: str) -> bool:
        """Ses dosyasını depolamadan siler."""
        pass


class ITranscriptRepository(ABC):
    """İlişkisel Veritabanı (PostgreSQL / SQLite) Repository Soyut Arayüzü."""

    @abstractmethod
    def save_record(self, record: AudioRecord) -> AudioRecord:
        """Yeni bir ses kaydı meta verisini veritabanına ekler."""
        pass

    @abstractmethod
    def get_record_by_id(self, record_id: uuid.UUID) -> Optional[AudioRecord]:
        """ID'ye göre ses kaydı ve zaman damgalı konuşmacı metinlerini getirir."""
        pass

    @abstractmethod
    def update_status(
        self, record_id: uuid.UUID, status: JobStatus, error_message: Optional[str] = None
    ) -> bool:
        """İş durumunu (PENDING, PROCESSING, COMPLETED, FAILED) günceller."""
        pass

    @abstractmethod
    def save_utterances(
        self, record_id: uuid.UUID, utterances: List[TranscriptUtterance], language: Optional[str] = None
    ) -> bool:
        """Analiz sonucu oluşan konuşmacı metinlerini kaydedip durumu COMPLETED yapar."""
        pass

    @abstractmethod
    def update_utterance(
        self, record_id: uuid.UUID, utterance_index: int, speaker_id: str, text: str
    ) -> bool:
        """Belirtilen indeksteki konuşmacı ve metin bilgisini günceller."""
        pass

    @abstractmethod
    def delete_utterance(self, record_id: uuid.UUID, utterance_index: int) -> bool:
        """Belirtilen indeksteki konuşmacı bloğunu siler."""
        pass

    @abstractmethod
    def add_utterance(self, record_id: uuid.UUID, utterance: TranscriptUtterance) -> bool:
        """Ses kaydına yeni bir konuşmacı bloğu ekler."""
        pass


class ISTTEngine(ABC):
    """Speech-to-Text Motor Arayüzü (Whisper vb.)."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        """
        Ses dosyasını işleyip kelime seviyesinde zaman damgalı segmentler ve tespit edilen dili döner.
        Returns: (List[WordSegment], detected_language)
        """
        pass


class IDiarizer(ABC):
    """Speaker Diarization Motor Arayüzü (PyAnnote vb.)."""

    @abstractmethod
    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        """Ses dosyasını işleyip konuşmacı zaman aralıklarını döner."""
        pass


class IAudioProcessor(ABC):
    """Ses Ön İşleme ve Normalizasyon Arayüzü (Rust PyO3 / NumPy / SciPy)."""

    @abstractmethod
    def normalize_and_resample(
        self, input_path: str, output_path: str, target_sample_rate: int = 16000
    ) -> str:
        """Gelen sesi 16kHz Mono WAV formatına dönüştürür ve normalize eder."""
        pass


class IVADProcessor(ABC):
    """Voice Activity Detection (Ses Algılama) Arayüzü (Silero VAD / Rust PyO3)."""

    @abstractmethod
    def get_speech_timestamps(
        self, audio_path: str, min_silence_duration_ms: int = 400
    ) -> List[Tuple[float, float]]:
        """
        Ses dosyasındaki konuşma aralıklarını (start_sec, end_sec) döner.
        Cümle sonu sessizlik noktalarından tam parçalama sağlar.
        """
        pass
