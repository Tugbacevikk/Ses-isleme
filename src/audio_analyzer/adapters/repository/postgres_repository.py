import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from audio_analyzer.adapters.repository.models import (
    AudioRecordModel,
    TranscriptUtteranceModel,
    WebhookDeliveryModel,
)
from audio_analyzer.domain.interfaces import (
    ITranscriptRepository,
    IWebhookOutboxRepository,
)
from audio_analyzer.domain.models import (
    AudioRecord,
    JobStatus,
    OverlapSummary,
    TranscriptUtterance,
)


class PostgresRepository(ITranscriptRepository, IWebhookOutboxRepository):
    """
    SQLAlchemy ile PostgreSQL (asyncpg) / SQLite (aiosqlite) asenkron veritabanı adaptörü.
    Clean Architecture gereği ORM nesneleri ile Domain modelleri arasında dönüşüm yapar.
    FastAPI event loop'unu bloklamayan %100 non-blocking asenkron okuma/yazma yürütür.
    """

    def __init__(self, session: AsyncSession, autocommit: bool = True):
        self.session = session
        self.autocommit = autocommit

    async def _commit_or_flush(self):
        if self.autocommit:
            await self.session.commit()
        else:
            await self.session.flush()

    async def save_record(self, record: AudioRecord) -> AudioRecord:
        overlap_str = None
        if record.overlap_summary:
            if hasattr(record.overlap_summary, "model_dump"):
                overlap_str = json.dumps(record.overlap_summary.model_dump())
            elif hasattr(record.overlap_summary, "dict"):
                overlap_str = json.dumps(record.overlap_summary.dict())

        orm_model = AudioRecordModel(
            id=record.id,
            external_id=record.external_id,
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
            attempts=record.attempts,
            processing_started_at=record.processing_started_at,
            last_error_at=record.last_error_at,
            overlap_summary=overlap_str,
            num_speakers=record.num_speakers,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self.session.add(orm_model)
        await self._commit_or_flush()
        return self._to_domain(orm_model)

    async def get_record_by_id(self, record_id: uuid.UUID) -> AudioRecord | None:
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

    async def get_record_by_external_id(self, external_id: str) -> AudioRecord | None:
        stmt = (
            select(AudioRecordModel)
            .where(AudioRecordModel.external_id == external_id)
            .options(selectinload(AudioRecordModel.utterances))
        )
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return None
        return self._to_domain(orm_model)

    async def create_webhook_delivery(self, job_id: uuid.UUID, url: str, payload: str) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        delivery_id = uuid.uuid4()
        orm_model = WebhookDeliveryModel(
            id=delivery_id,
            job_id=job_id,
            url=url,
            payload=payload,
            attempts=0,
            next_attempt_at=now,
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self.session.add(orm_model)
        await self._commit_or_flush()
        return delivery_id

    async def get_due_webhook_deliveries(self, limit: int = 50) -> list[dict]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(WebhookDeliveryModel)
            .where(
                WebhookDeliveryModel.status == "PENDING",
                WebhookDeliveryModel.next_attempt_at <= now,
            )
            .order_by(WebhookDeliveryModel.next_attempt_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        orm_list = res.scalars().all()
        return [
            {
                "id": r.id,
                "job_id": r.job_id,
                "url": r.url,
                "payload": r.payload,
                "attempts": r.attempts,
                "next_attempt_at": r.next_attempt_at,
                "status": r.status,
                "error_message": r.error_message,
            }
            for r in orm_list
        ]

    async def update_webhook_delivery_status(
        self, delivery_id: uuid.UUID, status: str, attempts: int, next_attempt_at: object | None = None, error_message: str | None = None
    ) -> bool:
        stmt = select(WebhookDeliveryModel).where(WebhookDeliveryModel.id == delivery_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        orm_model.status = status
        orm_model.attempts = attempts
        orm_model.updated_at = datetime.now(timezone.utc)
        if next_attempt_at:
            orm_model.next_attempt_at = next_attempt_at
        if error_message is not None:
            orm_model.error_message = error_message

        await self._commit_or_flush()
        return True


    async def claim_job_atomically(
        self, record_id: uuid.UUID, stale_seconds: int = 1800
    ) -> tuple[bool, AudioRecord | None, bool]:
        record = await self.get_record_by_id(record_id)
        if not record:
            return False, None, False

        if record.status == JobStatus.COMPLETED:
            return True, record, True

        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(seconds=stale_seconds)

        stmt = (
            update(AudioRecordModel)
            .where(
                AudioRecordModel.id == record_id,
                (AudioRecordModel.status == JobStatus.PENDING.value)
                | (
                    (AudioRecordModel.status == JobStatus.PROCESSING.value)
                    & (AudioRecordModel.updated_at < stale_threshold)
                ),
            )
            .values(
                status=JobStatus.PROCESSING.value,
                processing_started_at=now,
                updated_at=now,
            )
        )

        res = await self.session.execute(stmt)
        affected = res.rowcount
        await self.session.commit()
        self.session.expire_all()

        if affected > 0:
            updated_record = await self.get_record_by_id(record_id)
            return True, updated_record or record, False
        else:
            current_record = await self.get_record_by_id(record_id)
            if current_record and current_record.status == JobStatus.COMPLETED:
                return True, current_record, True
            return False, current_record, False

    async def touch_processing(self, record_id: uuid.UUID, claim_token: object | None) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        if orm_model.status != JobStatus.PROCESSING.value:
            return False

        if claim_token is not None and orm_model.processing_started_at is not None:
            t1 = claim_token.isoformat() if hasattr(claim_token, "isoformat") else str(claim_token)
            t2 = orm_model.processing_started_at.isoformat() if hasattr(orm_model.processing_started_at, "isoformat") else str(orm_model.processing_started_at)
            if t1 != t2:
                return False

        orm_model.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def complete_job(
        self,
        record_id: uuid.UUID,
        claim_token: object | None,
        utterances: list[TranscriptUtterance],
        language: str | None = None,
        overlap_summary: object | None = None,
        webhook_payload: str | None = None,
    ) -> bool:
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        if orm_model.status == JobStatus.COMPLETED.value:
            if claim_token is not None and orm_model.processing_started_at is not None:
                t1 = claim_token.isoformat() if hasattr(claim_token, "isoformat") else str(claim_token)
                t2 = orm_model.processing_started_at.isoformat() if hasattr(orm_model.processing_started_at, "isoformat") else str(orm_model.processing_started_at)
                if t1 != t2:
                    return False
            return True

        if orm_model.status != JobStatus.PROCESSING.value:
            return False

        now = datetime.now(timezone.utc)

        # Atomic conditional UPDATE
        upd_stmt = (
            update(AudioRecordModel)
            .where(
                AudioRecordModel.id == record_id,
                AudioRecordModel.status == JobStatus.PROCESSING.value,
            )
        )
        if claim_token is not None:
            upd_stmt = upd_stmt.where(
                (AudioRecordModel.processing_started_at == claim_token)
                | (AudioRecordModel.processing_started_at.is_(None))
            )

        overlap_json = None
        if overlap_summary is not None:
            if hasattr(overlap_summary, "model_dump"):
                overlap_json = json.dumps(overlap_summary.model_dump())
            elif hasattr(overlap_summary, "dict"):
                overlap_json = json.dumps(overlap_summary.dict())
            elif isinstance(overlap_summary, dict):
                overlap_json = json.dumps(overlap_summary)
            elif isinstance(overlap_summary, str):
                overlap_json = overlap_summary

        val_map = {
            "status": JobStatus.COMPLETED.value,
            "error_message": None,
            "updated_at": now,
        }
        if language:
            val_map["language"] = language
        if overlap_json is not None:
            val_map["overlap_summary"] = overlap_json

        upd_stmt = upd_stmt.values(**val_map)
        upd_res = await self.session.execute(upd_stmt)

        if upd_res.rowcount == 0:
            # Token mismatch or status changed concurrently
            await self.session.rollback()
            return False

        # Clear existing utterances in transaction to avoid duplication
        await self.session.execute(
            delete(TranscriptUtteranceModel).where(TranscriptUtteranceModel.audio_record_id == record_id)
        )

        if utterances:
            u_models = [
                TranscriptUtteranceModel(
                    id=u.id or uuid.uuid4(),
                    audio_record_id=record_id,
                    speaker_id=u.speaker_id,
                    start_time=u.start_time,
                    end_time=u.end_time,
                    text=u.text,
                    created_at=u.created_at or now,
                )
                for u in utterances
            ]
            self.session.add_all(u_models)

        # Transactional Outbox: insert WebhookDeliveryModel in the SAME transaction
        if orm_model.callback_url and webhook_payload:
            delivery_id = uuid.uuid4()
            delivery = WebhookDeliveryModel(
                id=delivery_id,
                job_id=record_id,
                url=orm_model.callback_url,
                payload=webhook_payload,
                attempts=0,
                next_attempt_at=now,
                status="PENDING",
                created_at=now,
                updated_at=now,
            )
            self.session.add(delivery)

        await self.session.commit()
        return True

    async def update_status(
        self, record_id: uuid.UUID, status: JobStatus, error_message: str | None = None
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
        utterances: list[TranscriptUtterance],
        language: str | None = None,
    ) -> bool:
        return await self.complete_job(
            record_id=record_id,
            claim_token=None,
            utterances=utterances,
            language=language,
        )

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

    async def update_utterance_by_id(
        self, record_id: uuid.UUID, utterance_id: uuid.UUID, speaker_id: str, text: str
    ) -> bool:
        stmt = select(TranscriptUtteranceModel).where(
            TranscriptUtteranceModel.audio_record_id == record_id,
            TranscriptUtteranceModel.id == utterance_id,
        )
        res = await self.session.execute(stmt)
        orm_u = res.scalar_one_or_none()
        if not orm_u:
            return False
        orm_u.speaker_id = speaker_id
        orm_u.text = text
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

    async def delete_utterance_by_id(self, record_id: uuid.UUID, utterance_id: uuid.UUID) -> bool:
        stmt = select(TranscriptUtteranceModel).where(
            TranscriptUtteranceModel.audio_record_id == record_id,
            TranscriptUtteranceModel.id == utterance_id,
        )
        res = await self.session.execute(stmt)
        orm_u = res.scalar_one_or_none()
        if not orm_u:
            return False
        await self.session.delete(orm_u)
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

    async def list_records(self, skip: int = 0, limit: int = 20) -> list[AudioRecord]:
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

    async def get_expired_records(
        self, before: datetime, statuses: list[JobStatus] | None = None, limit: int = 100
    ) -> list[AudioRecord]:
        stmt = select(AudioRecordModel).where(AudioRecordModel.created_at < before)
        if statuses:
            status_vals = [s.value if hasattr(s, "value") else str(s) for s in statuses]
            stmt = stmt.where(AudioRecordModel.status.in_(status_vals))
        stmt = stmt.order_by(AudioRecordModel.created_at.asc()).limit(limit)
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

    async def handle_job_failure(
        self,
        record_id: uuid.UUID,
        error_message: str,
        is_transient: bool = True,
        max_attempts: int = 3,
        claim_token: object | None = None,
    ) -> tuple[int, bool]:
        """
        İş hatasını kaydeder ve deneme sayısını (attempts) artırır.
        Hata kalıcı ise veya maks deneme sayısı aşıldıysa durumu FAILED yapar (is_final=True).
        Aksi takdirde durumu PENDING yapar (is_final=False) ve yeniden denenmeye izin verir.
        Döner: (yeni_attempts, is_final_failed)
        """
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return 0, True

        if claim_token is not None and orm_model.processing_started_at is not None:
            t1 = claim_token.isoformat() if hasattr(claim_token, "isoformat") else str(claim_token)
            t2 = orm_model.processing_started_at.isoformat() if hasattr(orm_model.processing_started_at, "isoformat") else str(orm_model.processing_started_at)
            if t1 != t2:
                return getattr(orm_model, "attempts", 0) or 0, False

        now = datetime.now(timezone.utc)
        new_attempts = (orm_model.attempts or 0) + 1
        is_final = (not is_transient) or (new_attempts >= max_attempts)
        new_status = JobStatus.FAILED.value if is_final else JobStatus.PENDING.value

        upd_stmt = (
            update(AudioRecordModel)
            .where(
                AudioRecordModel.id == record_id,
                AudioRecordModel.status == JobStatus.PROCESSING.value,
            )
        )
        if claim_token is not None:
            upd_stmt = upd_stmt.where(
                (AudioRecordModel.processing_started_at == claim_token)
                | (AudioRecordModel.processing_started_at.is_(None))
            )

        upd_stmt = upd_stmt.values(
            attempts=new_attempts,
            last_error_at=now,
            error_message=error_message,
            updated_at=now,
            status=new_status,
        )

        upd_res = await self.session.execute(upd_stmt)
        if upd_res.rowcount == 0 and claim_token is not None:
            await self.session.rollback()
            return getattr(orm_model, "attempts", 0) or 0, False

        await self._commit_or_flush()
        return new_attempts, is_final

    async def get_stale_pending_records(self, stale_seconds: int = 300, limit: int = 50) -> list[AudioRecord]:
        """
        'stale_seconds' süresidir PENDING durumunda bekleyen kayıtları getirir.
        """
        threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        stmt = (
            select(AudioRecordModel)
            .where(
                AudioRecordModel.status == JobStatus.PENDING.value,
                AudioRecordModel.updated_at < threshold,
            )
            .order_by(AudioRecordModel.updated_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        orm_records = res.scalars().all()
        return [self._to_domain(r) for r in orm_records]

    async def touch_pending(self, record_id: uuid.UUID) -> bool:
        """PENDING durumundaki işin updated_at zamanını günceller."""
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False
        orm_model.updated_at = datetime.now(timezone.utc)
        await self._commit_or_flush()
        return True

    async def get_stale_processing_records(self, stale_seconds: int = 1800, limit: int = 50) -> list[AudioRecord]:
        """
        'stale_seconds' süresidir PROCESSING durumunda kalmış (çökmüş/askıda) kayıtları getirir.
        """
        threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        stmt = (
            select(AudioRecordModel)
            .where(
                AudioRecordModel.status == JobStatus.PROCESSING.value,
                AudioRecordModel.updated_at < threshold,
            )
            .order_by(AudioRecordModel.updated_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        orm_records = res.scalars().all()
        return [self._to_domain(r) for r in orm_records]

    async def reset_record_to_pending(self, record_id: uuid.UUID) -> bool:
        """
        Kayıt durumunu tekrar PENDING yapar (Sweeper yeniden kuyruğa almak için kullanır).
        """
        stmt = select(AudioRecordModel).where(AudioRecordModel.id == record_id)
        res = await self.session.execute(stmt)
        orm_model = res.scalar_one_or_none()
        if not orm_model:
            return False

        orm_model.status = JobStatus.PENDING.value
        orm_model.updated_at = datetime.now(timezone.utc)
        await self._commit_or_flush()
        return True

    def _to_domain(self, orm: AudioRecordModel) -> AudioRecord:
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
        overlap_summary_domain = None
        if getattr(orm, "overlap_summary", None):
            try:
                data = json.loads(orm.overlap_summary)
                overlap_summary_domain = OverlapSummary(**data)
            except Exception:
                pass

        return AudioRecord(
            id=orm.id,
            external_id=getattr(orm, "external_id", None),
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
            attempts=getattr(orm, "attempts", 0) or 0,
            processing_started_at=getattr(orm, "processing_started_at", None),
            last_error_at=getattr(orm, "last_error_at", None),
            overlap_summary=overlap_summary_domain,
            num_speakers=getattr(orm, "num_speakers", None),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            utterances=domain_utterances,
        )

