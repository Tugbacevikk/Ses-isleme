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
def in_memory_db():
    """Birim testler için bellek içi (in-memory) SQLite veritabanı fixture'ı."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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
