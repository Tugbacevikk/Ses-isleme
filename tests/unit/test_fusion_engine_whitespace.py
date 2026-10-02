from audio_analyzer.domain.models import DiarizationSegment, WordSegment
from audio_analyzer.services.fusion_engine import FusionEngine


def test_fusion_engine_no_double_spaces():
    engine = FusionEngine()
    words = [
        WordSegment(word=" Merhaba", start_time=0.0, end_time=0.5, confidence=0.9),
        WordSegment(word=" nasılsın", start_time=0.5, end_time=1.0, confidence=0.9),
    ]
    diarization = [DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0)]
    utterances = engine.align(words, diarization)

    assert len(utterances) == 1
    assert utterances[0].text == "Merhaba nasılsın"
