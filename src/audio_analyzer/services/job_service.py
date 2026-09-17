import traceback
import uuid
from typing import Optional

from audio_analyzer.domain.interfaces import IAudioStorage, ITranscriptRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.pipeline import AudioAnalysisPipeline


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

    def create_job(self, file_name: str, file_bytes: bytes) -> uuid.UUID:
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

            utterances, language = self.pipeline.process(local_audio_path)

            # Başarılı ise sonuçları ve dili kaydet (COMPLETED)
            self.repo.save_utterances(record_id, utterances, language=language)
            return True

        except Exception as ex:
            error_msg = f"{type(ex).__name__}: {str(ex)}\n{traceback.format_exc()}"
            self.repo.update_status(record_id, JobStatus.FAILED, error_message=error_msg)
            return False
