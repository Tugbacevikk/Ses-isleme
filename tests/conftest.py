import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.domain.models import DiarizationSegment, WordSegment


@pytest.fixture(autouse=True)
def enable_mock_stt_for_tests(monkeypatch):
    """Birim ve entegrasyon testlerinin RAM yetersizliğinden etkilenmemesi için ALLOW_MOCK_STT=true ayarlar."""
    monkeypatch.setenv("ALLOW_MOCK_STT", "true")


@pytest.fixture
async def in_memory_db():
    """Birim testler için asenkron bellek içi (in-memory) SQLite veritabanı fixture'ı."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncTestingSessionLocal = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
    )
    async with AsyncTestingSessionLocal() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_stt_words():
    """Örnek STT kelime listesi."""
    return [
        WordSegment(word="Merhaba", start_time=0.0, end_time=0.5),
        WordSegment(word="nasılsınız", start_time=0.6, end_time=1.2),
        WordSegment(word="Ben", start_time=1.3, end_time=1.5),
        WordSegment(word="iyiyim", start_time=1.6, end_time=2.0),
        WordSegment(
            word="Teşekkürler", start_time=4.0, end_time=4.8
        ),  # 2.0s - 4.0s arası sessizlik (>1.5s)
    ]


@pytest.fixture
def sample_diarization_segments():
    """Örnek konuşmacı zaman aralıkları."""
    return [
        DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=1.25),
        DiarizationSegment(speaker_id="SPEAKER_01", start_time=1.28, end_time=2.1),
        DiarizationSegment(speaker_id="SPEAKER_00", start_time=3.9, end_time=5.0),
    ]
