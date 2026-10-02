import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.api.dependencies import get_repository
from audio_analyzer.api.main import app
from audio_analyzer.domain.models import AudioRecord, JobStatus, TranscriptUtterance


@pytest.mark.asyncio
async def test_utterance_uuid_endpoints():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        repo = PostgresRepository(session, autocommit=True)

        rec_id = uuid.uuid4()
        utt_id1 = uuid.uuid4()
        utt_id2 = uuid.uuid4()

        u1 = TranscriptUtterance(id=utt_id1, speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Merhaba")
        u2 = TranscriptUtterance(id=utt_id2, speaker_id="SPEAKER_01", start_time=1.0, end_time=2.0, text="Nasılsın")

        record = AudioRecord(
            id=rec_id,
            storage_uri="/path/test.wav",
            file_name="test.wav",
            status=JobStatus.COMPLETED,
        )

        await repo.save_record(record)
        await repo.add_utterance(rec_id, u1)
        await repo.add_utterance(rec_id, u2)

        # Override dependency
        async def override_get_repository():
            yield repo

        app.dependency_overrides[get_repository] = override_get_repository

        client = TestClient(app)

        # 1. Test GET /api/v1/jobs/{job_id} returns utterance id
        res = client.get(f"/api/v1/jobs/{rec_id}")
        assert res.status_code == 200
        data = res.json()
        assert len(data["utterances"]) == 2
        assert data["utterances"][0]["id"] == str(utt_id1)

        # 2. Test PUT /api/v1/jobs/{job_id}/utterances/{utterance_id}
        put_res = client.put(
            f"/api/v1/jobs/{rec_id}/utterances/{utt_id1}",
            json={"speaker_id": "SPEAKER_99", "text": "Merhaba Düzeltildi"},
        )
        assert put_res.status_code == 200

        # Verify update in DB
        updated_rec = await repo.get_record_by_id(rec_id)
        assert updated_rec.utterances[0].speaker_id == "SPEAKER_99"
        assert updated_rec.utterances[0].text == "Merhaba Düzeltildi"

        # 3. Test DELETE /api/v1/jobs/{job_id}/utterances/{utterance_id}
        del_res = client.delete(f"/api/v1/jobs/{rec_id}/utterances/{utt_id2}")
        assert del_res.status_code == 200

        # Verify deletion in DB
        updated_rec = await repo.get_record_by_id(rec_id)
        assert len(updated_rec.utterances) == 1

        app.dependency_overrides.clear()
