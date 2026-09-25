import uuid
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from audio_analyzer.adapters.repository.models import AudioRecordModel, TranscriptUtteranceModel
from audio_analyzer.domain.interfaces import ITranscriptRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus, TranscriptUtterance

import time
from sqlalchemy.exc import OperationalError

class PostgresRepository(ITranscriptRepository):
    """
    SQLAlchemy ile PostgreSQL (asyncpg) / SQLite (aiosqlite) asenkron veritabanı adaptörü.
    Clean Architecture gereği ORM nesneleri ile Domain modelleri arasında dönüşüm yapar.
    FastAPI event loop'unu bloklamayan %100 non-blocking asenkron okuma/yazma yürütür.
    """

    def __init__(self, session: AsyncSession, autocommit: bool = True):
        self.session = session
        self.autocommit = autocommit

    async def _commit_or_flush(self):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                if self.autocommit:
                    await self.session.commit()
                else:
                    await self.session.flush()
                break
            except OperationalError as ex:
                if "locked" in str(ex).lower() and attempt < max_retries - 1:
                    import asyncio

                    await asyncio.sleep(0.2 * (attempt + 1))
                else:
                    raise

    async def save_record(self, record: AudioRecord) -> AudioRecord:
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
            callback_url=record.callback_url,
            webhook_status=record.webhook_status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self.session.add(orm_model)
        await self._commit_or_flush()
        return self._to_domain(orm_model)

    async def get_record_by_id(self, record_id: uuid.UUID) -> Optional[AudioRecord]:
        stmt = (
            select(AudioRecordModel)
            .where(AudioRecordModel.id == record_id)
            .options(selectinload(AudioRecordModel.utterances))
        )
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return None
        return self._to_domain(orm_model)

    async def update_status(
        self, record_id: uuid.UUID, status: JobStatus, error_message: Optional[str] = None
    ) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        orm_model.status = status.value
        if error_message is not None:
            orm_model.error_message = error_message

        await self._commit_or_flush()
        return True

    async def save_utterances(
        self,
        record_id: uuid.UUID,
        utterances: List[TranscriptUtterance],
        language: Optional[str] = None,
    ) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        if utterances:
            u_models = [
                TranscriptUtteranceModel(
                    id=u.id,
                    audio_record_id=record_id,
                    speaker_id=u.speaker_id,
                    start_time=u.start_time,
                    end_time=u.end_time,
                    text=u.text,
                    created_at=u.created_at,
                )
                for u in utterances
            ]
            self.session.add_all(u_models)

        orm_model.status = JobStatus.COMPLETED.value
        if language:
            orm_model.language = language

        await self._commit_or_flush()
        return True

    async def update_utterance(
        self, record_id: uuid.UUID, utterance_index: int, speaker_id: str, text: str
    ) -> bool:
        stmt = (
            select(TranscriptUtteranceModel)
            .where(TranscriptUtteranceModel.audio_record_id == record_id)
            .order_by(
                TranscriptUtteranceModel.start_time.asc(),
                TranscriptUtteranceModel.created_at.asc(),
                TranscriptUtteranceModel.id.asc(),
            )
        )
        res = await self.session.execute(stmt)
        orm_utterances = list(res.scalars().all())

        if not orm_utterances or utterance_index < 0 or utterance_index >= len(orm_utterances):
            return False

        orm_utterances[utterance_index].speaker_id = speaker_id
        orm_utterances[utterance_index].text = text
        await self._commit_or_flush()
        return True

    async def delete_utterance(self, record_id: uuid.UUID, utterance_index: int) -> bool:
        stmt = (
            select(TranscriptUtteranceModel)
            .where(TranscriptUtteranceModel.audio_record_id == record_id)
            .order_by(
                TranscriptUtteranceModel.start_time.asc(),
                TranscriptUtteranceModel.created_at.asc(),
                TranscriptUtteranceModel.id.asc(),
            )
        )
        res = await self.session.execute(stmt)
        orm_utterances = list(res.scalars().all())

        if not orm_utterances or utterance_index < 0 or utterance_index >= len(orm_utterances):
            return False

        await self.session.delete(orm_utterances[utterance_index])
        await self._commit_or_flush()
        return True

    async def add_utterance(self, record_id: uuid.UUID, utterance: TranscriptUtterance) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
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
        await self._commit_or_flush()
        return True

    async def list_records(self, skip: int = 0, limit: int = 20) -> List[AudioRecord]:
        stmt = (
            select(AudioRecordModel)
            .options(selectinload(AudioRecordModel.utterances))
            .order_by(AudioRecordModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        orm_records = res.scalars().all()
        return [self._to_domain(r) for r in orm_records]

    async def delete_record(self, record_id: uuid.UUID) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False
        await self.session.delete(orm_model)
        await self._commit_or_flush()
        return True

    def _to_domain(self, orm: AudioRecordModel) -> AudioRecord:
        from datetime import datetime
        from sqlalchemy import inspect

        state = inspect(orm)
        if state is not None and "utterances" in state.unloaded:
            utterances_list = []
        else:
            utterances_list = list(getattr(orm, "utterances", []) or [])

        sorted_utterances = sorted(
            utterances_list,
            key=lambda u: (u.start_time, u.created_at or datetime.min, str(u.id)),
        )
        domain_utterances = [
            TranscriptUtterance(
                id=u.id,
                speaker_id=u.speaker_id,
                start_time=u.start_time,
                end_time=u.end_time,
                text=u.text,
                created_at=u.created_at,
            )
            for u in sorted_utterances
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
            callback_url=getattr(orm, "callback_url", None),
            webhook_status=getattr(orm, "webhook_status", None),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            utterances=domain_utterances,
        )
