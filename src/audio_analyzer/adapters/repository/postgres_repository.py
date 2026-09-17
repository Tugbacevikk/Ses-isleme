import uuid
from typing import List, Optional
from sqlalchemy.orm import Session
from audio_analyzer.domain.interfaces import ITranscriptRepository
from audio_analyzer.domain.models import AudioRecord, TranscriptUtterance, JobStatus
from audio_analyzer.adapters.repository.models import AudioRecordModel, TranscriptUtteranceModel


class PostgresRepository(ITranscriptRepository):
    """
    SQLAlchemy ile PostgreSQL / SQLite veritabanı adaptörü.
    Clean Architecture gereği ORM nesneleri ile Domain modelleri arasında dönüşüm yapar.
    """

    def __init__(self, session: Session):
        self.session = session

    def save_record(self, record: AudioRecord) -> AudioRecord:
        orm_model = AudioRecordModel(
            id=record.id,
            storage_uri=record.storage_uri,
            file_name=record.file_name,
            duration_seconds=record.duration_seconds,
            sample_rate=record.sample_rate,
            channels=record.channels,
            language=record.language,
            status=record.status.value,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self.session.add(orm_model)
        self.session.commit()
        self.session.refresh(orm_model)
        return self._to_domain(orm_model)

    def get_record_by_id(self, record_id: uuid.UUID) -> Optional[AudioRecord]:
        orm_model = (
            self.session.query(AudioRecordModel)
            .filter(AudioRecordModel.id == record_id)
            .first()
        )
        if not orm_model:
            return None
        return self._to_domain(orm_model)

    def update_status(
        self, record_id: uuid.UUID, status: JobStatus, error_message: Optional[str] = None
    ) -> bool:
        orm_model = (
            self.session.query(AudioRecordModel)
            .filter(AudioRecordModel.id == record_id)
            .first()
        )
        if not orm_model:
            return False
        
        orm_model.status = status.value
        if error_message is not None:
            orm_model.error_message = error_message
        
        self.session.commit()
        return True

    def save_utterances(
        self, record_id: uuid.UUID, utterances: List[TranscriptUtterance], language: Optional[str] = None
    ) -> bool:
        orm_model = (
            self.session.query(AudioRecordModel)
            .filter(AudioRecordModel.id == record_id)
            .first()
        )
        if not orm_model:
            return False

        # Cümleleri ekle
        for u in utterances:
            u_model = TranscriptUtteranceModel(
                id=u.id,
                audio_record_id=record_id,
                speaker_id=u.speaker_id,
                start_time=u.start_time,
                end_time=u.end_time,
                text=u.text,
                created_at=u.created_at,
            )
            self.session.add(u_model)

        orm_model.status = JobStatus.COMPLETED.value
        if language:
            orm_model.language = language

        self.session.commit()
        return True

    def update_utterance(
        self, record_id: uuid.UUID, utterance_index: int, speaker_id: str, text: str
    ) -> bool:
        orm_utterances = (
            self.session.query(TranscriptUtteranceModel)
            .filter(TranscriptUtteranceModel.audio_record_id == record_id)
            .order_by(TranscriptUtteranceModel.start_time.asc())
            .all()
        )
        if not orm_utterances or utterance_index < 0 or utterance_index >= len(orm_utterances):
            return False

        orm_utterances[utterance_index].speaker_id = speaker_id
        orm_utterances[utterance_index].text = text
        self.session.commit()
        return True

    def delete_utterance(self, record_id: uuid.UUID, utterance_index: int) -> bool:
        orm_utterances = (
            self.session.query(TranscriptUtteranceModel)
            .filter(TranscriptUtteranceModel.audio_record_id == record_id)
            .order_by(TranscriptUtteranceModel.start_time.asc())
            .all()
        )
        if not orm_utterances or utterance_index < 0 or utterance_index >= len(orm_utterances):
            return False

        self.session.delete(orm_utterances[utterance_index])
        self.session.commit()
        return True

    def add_utterance(self, record_id: uuid.UUID, utterance: TranscriptUtterance) -> bool:
        record = (
            self.session.query(AudioRecordModel)
            .filter(AudioRecordModel.id == record_id)
            .first()
        )
        if not record:
            return False

        new_u = TranscriptUtteranceModel(
            id=utterance.id or uuid.uuid4(),
            audio_record_id=record_id,
            speaker_id=utterance.speaker_id,
            start_time=utterance.start_time,
            end_time=utterance.end_time,
            text=utterance.text,
            created_at=utterance.created_at,
        )
        self.session.add(new_u)
        self.session.commit()
        return True

    def _to_domain(self, orm: AudioRecordModel) -> AudioRecord:
        domain_utterances = [
            TranscriptUtterance(
                id=u.id,
                speaker_id=u.speaker_id,
                start_time=u.start_time,
                end_time=u.end_time,
                text=u.text,
                created_at=u.created_at,
            )
            for u in orm.utterances
        ]
        return AudioRecord(
            id=orm.id,
            storage_uri=orm.storage_uri,
            file_name=orm.file_name,
            duration_seconds=orm.duration_seconds,
            sample_rate=orm.sample_rate,
            channels=orm.channels,
            language=orm.language,
            status=JobStatus(orm.status),
            error_message=orm.error_message,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            utterances=domain_utterances,
        )
