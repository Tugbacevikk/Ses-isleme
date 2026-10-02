import uuid

import pytest

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.models import AudioRecord, JobStatus, TranscriptUtterance


@pytest.mark.integration
async def test_postgres_repository_crud_flow(in_memory_db):
    """Repository entegrasyonunun SQLite (in-memory) üzerinde eksiksiz çalıştığını doğrular."""
    repo = PostgresRepository(session=in_memory_db)

    # 1. Yeni Kayıt Ekleme
    record_id = uuid.uuid4()
    new_record = AudioRecord(
        id=record_id,
        storage_uri="file:///storage/raw/test.wav",
        file_name="test.wav",
        duration_seconds=10.5,
        status=JobStatus.PENDING,
    )
    saved_record = await repo.save_record(new_record)
    assert saved_record.id == record_id
    assert saved_record.status == JobStatus.PENDING

    # 2. Durum Güncelleme (PROCESSING)
    updated = await repo.update_status(record_id, JobStatus.PROCESSING)
    assert updated is True
    record_fetched = await repo.get_record_by_id(record_id)
    assert record_fetched.status == JobStatus.PROCESSING

    # 3. Utterances Kaydetme ve Tamamlama (COMPLETED)
    utterances = [
        TranscriptUtterance(
            speaker_id="SPEAKER_00", start_time=0.0, end_time=2.5, text="Merhaba dunya"
        )
    ]
    saved_utt = await repo.save_utterances(record_id, utterances, language="tr")
    assert saved_utt is True

    # 4. Doğrulama
    final_record = await repo.get_record_by_id(record_id)
    assert final_record.status == JobStatus.COMPLETED
    assert final_record.language == "tr"
    assert len(final_record.utterances) == 1
    assert final_record.utterances[0].text == "Merhaba dunya"


@pytest.mark.integration
async def test_init_engine_fallback_behavior(monkeypatch):
    from audio_analyzer.api import dependencies
    from audio_analyzer.api.dependencies import create_async_db_engine, init_engine
    from audio_analyzer.api.main import app, lifespan

    invalid_url = "postgresql://invalid_user:invalid_pass@localhost:9999/non_existent_db"
    monkeypatch.setenv("DATABASE_URL", invalid_url)

    # 1. init_engine her zaman varsayılan olarak DATABASE_URL ile engine oluşturmalı
    pg_engine = init_engine()
    assert "postgresql" in str(pg_engine.url)

    # 2. ALLOW_SQLITE_FALLBACK=true iken lifespan sırasında SQLite yedeğine düşülmeli
    monkeypatch.setenv("ALLOW_SQLITE_FALLBACK", "true")
    dependencies.engine = create_async_db_engine(invalid_url)

    async with lifespan(app):
        assert "sqlite" in str(dependencies.engine.url)


