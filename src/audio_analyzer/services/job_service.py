import logging
import re
import uuid
from typing import Optional

from audio_analyzer.domain.interfaces import IAudioStorage, ITranscriptRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.pipeline import AudioAnalysisPipeline

logger = logging.getLogger(__name__)


def sanitize_error_message(ex: Exception) -> str:
    """
    Sistem dosya yollarını, sunucu dizin yapısını ve iç detayları sızdırmamak
    için kullanıcıya dönecek hata mesajını temizler.
    """
    err_type = type(ex).__name__
    err_str = str(ex)

    # Windows ve Unix mutlak dosya yollarını maskele (örn. C:\Users\... veya /var/...)
    err_str = re.sub(r'[A-Za-z]:\\[^\s:]+', '[FILE_PATH]', err_str)
    err_str = re.sub(r'/(?:[^\s:]+/)+[^\s:]+', '[FILE_PATH]', err_str)

    return f"{err_type}: {err_str}"


class JobService:
    """
    Ses Analiz İşleri ve Görev Yaşam Döngüsü Servisi (Job Lifecycle Service).
    Kullanıcı taleplerini alır, veritabanı durumlarını ve dosya depolamayı yönetir.
    """

    def __init__(
        self,
        storage: IAudioStorage,
        repository: ITranscriptRepository,
        pipeline: Optional[AudioAnalysisPipeline] = None,
    ):
        self.storage = storage
        self.repo = repository
        self.pipeline = pipeline

    def create_job(self, file_name: str, file_bytes: bytes, callback_url: Optional[str] = None) -> uuid.UUID:
        """
        Yeni bir analiz görevi oluşturur (status='PENDING').
        Ses dosyasını depolamaya kaydeder ve DB kaydını açar.
        """
        storage_uri = self.storage.save(file_bytes, file_name)
        record_id = uuid.uuid4()

        record = AudioRecord(
            id=record_id,
            storage_uri=storage_uri,
            file_name=file_name,
            status=JobStatus.PENDING,
            callback_url=callback_url,
        )
        saved = self.repo.save_record(record)
        return saved.id

    def execute_job(self, record_id: uuid.UUID) -> bool:
        """
        Arka plan worker'ı tarafından çağrılır.
        Durumu 'PROCESSING' yapar, pipeline'ı çalıştırır ve 'COMPLETED' veya 'FAILED' yazar.
        """
        record = self.repo.get_record_by_id(record_id)
        if not record:
            return False

        # Durumu PROCESSING yap
        self.repo.update_status(record_id, JobStatus.PROCESSING)

        try:
            local_audio_path = self.storage.get_path(record.storage_uri)

            # Pipeline çalıştır
            if self.pipeline is None:
                from audio_analyzer.services.pipeline_factory import get_shared_pipeline

                self.pipeline = get_shared_pipeline()

            utterances, language, overlap_summary = self.pipeline.process(local_audio_path)

            # Başarılı ise sonuçları ve dili kaydet (COMPLETED)
            self.repo.save_utterances(record_id, utterances, language=language)
            return True

        except Exception as ex:
            logger.error("Job execution failed for job_id=%s: %s", record_id, ex, exc_info=True)
            sanitized_msg = sanitize_error_message(ex)
            self.repo.update_status(record_id, JobStatus.FAILED, error_message=sanitized_msg)
            return False

