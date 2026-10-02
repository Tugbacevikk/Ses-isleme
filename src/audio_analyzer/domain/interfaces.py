import uuid
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from audio_analyzer.domain.models import (
    AudioRecord,
    DiarizationSegment,
    JobStatus,
    TranscriptUtterance,
    WordSegment,
)


class IAudioStorage(ABC):
    """Nesne Depolama (Object Storage / Local FS / RAM Buffer) Soyut Arayüzü."""

    @abstractmethod
    def save(self, file_bytes: bytes, file_name: str) -> str:
        """Ses dosyasını depolar ve benzersiz bir storage_uri döner."""
        pass

    @abstractmethod
    def get_path(self, storage_uri: str) -> str:
        """storage_uri'den yerel erişilebilir dosya yolunu döner."""
        pass

    @abstractmethod
    def get_bytes(self, storage_uri: str) -> bytes:
        """storage_uri'den ses verisini fiziksel diske yazmadan doğrudan RAM bayt akışı olarak döner."""
        pass

    @abstractmethod
    def delete(self, storage_uri: str) -> bool:
        """Ses dosyasını depolamadan siler."""
        pass


class IWebhookOutboxRepository(ABC):
    """Transactional Outbox deseni için Webhook teslimat yönetim soyut arayüzü (ISP Uyumlu)."""

    @abstractmethod
    async def create_webhook_delivery(self, job_id: uuid.UUID, url: str, payload: str) -> uuid.UUID:
        """Outbox deseni için webhook teslimat kaydı oluşturur."""
        pass

    @abstractmethod
    async def get_due_webhook_deliveries(self, limit: int = 50) -> List[dict]:
        """Teslimat zamanı gelmiş PENDING durumdaki webhook kayıtlarını getirir."""
        pass

    @abstractmethod
    async def update_webhook_delivery_status(
        self, delivery_id: uuid.UUID, status: str, attempts: int, next_attempt_at: Optional[object] = None, error_message: Optional[str] = None
    ) -> bool:
        """Webhook teslimat durumunu günceller."""
        pass


class ITranscriptRepository(IWebhookOutboxRepository, ABC):
    """İlişkisel Veritabanı (PostgreSQL / SQLite) Asenkron Repository Soyut Arayüzü."""

    @abstractmethod
    async def save_record(self, record: AudioRecord) -> AudioRecord:
        """Yeni bir ses kaydı meta verisini veritabanına ekler."""
        pass

    @abstractmethod
    async def get_record_by_id(self, record_id: uuid.UUID) -> Optional[AudioRecord]:
        """ID'ye göre ses kaydı ve zaman damgalı konuşmacı metinlerini getirir."""
        pass

    @abstractmethod
    async def get_record_by_external_id(self, external_id: str) -> Optional[AudioRecord]:
        """Dış sistem ID'sine (external_id) göre ses kaydını getirir (Idempotency tespiti)."""
        pass


    @abstractmethod
    async def claim_job_atomically(
        self, record_id: uuid.UUID, stale_seconds: int = 1800
    ) -> Tuple[bool, Optional[AudioRecord], bool]:
        """İşi atomik olarak PENDING -> PROCESSING yapar (claimed, record, is_completed döner)."""
        pass

    @abstractmethod
    async def update_status(
        self, record_id: uuid.UUID, status: JobStatus, error_message: Optional[str] = None
    ) -> bool:
        """İş durumunu (PENDING, PROCESSING, COMPLETED, FAILED) günceller."""
        pass

    @abstractmethod
    async def handle_job_failure(
        self,
        record_id: uuid.UUID,
        error_message: str,
        is_transient: bool = True,
        max_attempts: int = 3,
    ) -> Tuple[int, bool]:
        """İş hatasını kaydeder, attempts artırır ve durumu (FAILED veya PENDING) belirler."""
        pass

    @abstractmethod
    async def get_stale_pending_records(self, stale_seconds: int = 300, limit: int = 50) -> List[AudioRecord]:
        """PENDING durumunda bekleyen bayat kayıtları getirir."""
        pass

    @abstractmethod
    async def get_stale_processing_records(self, stale_seconds: int = 1800, limit: int = 50) -> List[AudioRecord]:
        """PROCESSING durumunda kalmış bayat kayıtları getirir."""
        pass

    @abstractmethod
    async def reset_record_to_pending(self, record_id: uuid.UUID) -> bool:
        """Kayıt durumunu tekrar PENDING yapar."""
        pass

    @abstractmethod
    async def save_utterances(
        self,
        record_id: uuid.UUID,
        utterances: List[TranscriptUtterance],
        language: Optional[str] = None,
    ) -> bool:
        """Analiz sonucu oluşan konuşmacı metinlerini kaydedip durumu COMPLETED yapar."""
        pass

    @abstractmethod
    async def complete_job(
        self,
        record_id: uuid.UUID,
        claim_token: Optional[object],
        utterances: List[TranscriptUtterance],
        language: Optional[str] = None,
        overlap_summary: Optional[object] = None,
        webhook_payload: Optional[str] = None,
    ) -> bool:
        """Kayıt durumunu COMPLETED yapar, mevcut utterance'ları temizleyip yenilerini atomik ekler ve outbox kaydı oluşturur."""
        pass

    @abstractmethod
    async def touch_processing(self, record_id: uuid.UUID, claim_token: Optional[object]) -> bool:
        """PROCESSING durumundaki işin updated_at zamanını günceller (Heartbeat)."""
        pass

    @abstractmethod
    async def update_utterance(
        self, record_id: uuid.UUID, utterance_index: int, speaker_id: str, text: str
    ) -> bool:
        """Belirtilen indeksteki konuşmacı ve metin bilgisini günceller."""
        pass

    @abstractmethod
    async def delete_utterance(self, record_id: uuid.UUID, utterance_index: int) -> bool:
        """Belirtilen indeksteki konuşmacı bloğunu siler."""
        pass

    @abstractmethod
    async def add_utterance(self, record_id: uuid.UUID, utterance: TranscriptUtterance) -> bool:
        """Ses kaydına yeni bir konuşmacı bloğu ekler."""
        pass

    @abstractmethod
    async def list_records(self, skip: int = 0, limit: int = 20) -> List[AudioRecord]:
        """Tüm ses kayıtlarını tarihe göre tersten sıralı ve sayfalamalı getirir."""
        pass

    @abstractmethod
    async def delete_record(self, record_id: uuid.UUID) -> bool:
        """Ses kaydını ve bağlı tüm konuşmacı metinlerini veritabanından siler."""
        pass


class IUnitOfWork(ABC):
    """Unit of Work (İş Birimi) Asenkron İşlem ve Transaction Yönetimi Arayüzü."""

    repository: ITranscriptRepository

    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    async def commit(self):
        """Transaction değişikliklerini veritabanına kaydeder."""
        pass

    @abstractmethod
    async def rollback(self):
        """Hata durumunda transaction değişikliklerini geri alır."""
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


class IAudioDenoiser(ABC):
    """Ses Ön Gürültü Temizleme (Denoising) Soyut Arayüzü."""

    @abstractmethod
    def denoise(self, input_path: str, output_path: str) -> str:
        """
        Ses dosyasındaki arka plan gürültülerini temizler ve çıktı dosya yolunu döner.
        """
        pass

