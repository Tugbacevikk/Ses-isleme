import pytest
from typing import List, Tuple, Optional
from audio_analyzer.domain.interfaces import ISTTEngine, IDiarizer
from audio_analyzer.domain.models import WordSegment, DiarizationSegment
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.services.job_service import JobService


class MockSTTEngine(ISTTEngine):
    """Sistem testleri için taklit STT motoru."""
    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        words = [
            WordSegment(word="Alo", start_time=0.0, end_time=0.4),
            WordSegment(word="buyurun", start_time=0.5, end_time=0.9),
            WordSegment(word="Nasıl", start_time=1.0, end_time=1.3),
            WordSegment(word="yardımcı", start_time=1.4, end_time=1.8),
            WordSegment(word="olabilirim", start_time=1.9, end_time=2.5),
        ]
        return words, "tr"


class MockDiarizer(IDiarizer):
    """Sistem testleri için taklit Diarization motoru."""
    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        return [
            DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=0.95),
            DiarizationSegment(speaker_id="SPEAKER_01", start_time=0.98, end_time=2.6),
        ]


@pytest.mark.system
def test_full_job_service_pipeline_e2e(tmp_path, in_memory_db):
    """
    Tüm sistem bileşenlerinin (Storage + DB Repo + Pipeline + FusionEngine + JobService)
    uçtan uca (E2E) mükemmel bir şekilde bir arada çalıştığını doğrular.
    """
    # 1. Adaptörlerin ve servislerin ayağa kaldırılması (Dependency Injection)
    storage = LocalStorageAdapter(base_dir=str(tmp_path / "storage"))
    repository = PostgresRepository(session=in_memory_db)
    stt_engine = MockSTTEngine()
    diarizer = MockDiarizer()
    pipeline = AudioAnalysisPipeline(stt_engine=stt_engine, diarizer=diarizer)

    job_service = JobService(storage=storage, repository=repository, pipeline=pipeline)

    # 2. İstemci Talebi (Ses Dosyası Yükleme & PENDING Görev Oluşturma)
    mock_audio_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    job_id = job_service.create_job(file_name="ornek_cagri.wav", file_bytes=mock_audio_bytes)

    record_pending = repository.get_record_by_id(job_id)
    assert record_pending is not None
    assert record_pending.status.value == "PENDING"

    # 3. Arka Plan Worker Tarafından Görevin İşlenmesi (execute_job)
    success = job_service.execute_job(job_id)
    assert success is True

    # 4. Veritabanı Sonuçlarının Doğrulanması (COMPLETED)
    record_completed = repository.get_record_by_id(job_id)
    assert record_completed.status.value == "COMPLETED"
    assert record_completed.language == "tr"
    assert len(record_completed.utterances) == 2

    # Konuşmacı 0 (Müşteri/Arayan): "Alo buyurun"
    assert record_completed.utterances[0].speaker_id == "SPEAKER_00"
    assert record_completed.utterances[0].text == "Alo buyurun"

    # Konuşmacı 1 (Temsilci): "Nasıl yardımcı olabilirim"
    assert record_completed.utterances[1].speaker_id == "SPEAKER_01"
    assert record_completed.utterances[1].text == "Nasıl yardımcı olabilirim"
