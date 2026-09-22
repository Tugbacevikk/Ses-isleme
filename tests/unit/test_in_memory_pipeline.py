import pytest
from audio_analyzer.utils.audio_io import create_synthetic_wav_bytes
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.adapters.stt.mock_stt_adapter import MockSTTAdapter
from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer
from audio_analyzer.adapters.audio.audio_converter import AudioConverterProcessor


@pytest.mark.unit
def test_pipeline_process_bytes_in_memory():
    """0-Disk I/O In-Memory Stream Pipeline metodunun doğrulanması."""
    stt_engine = MockSTTAdapter()
    diarizer = SpeechBrainECAPADiarizer()
    audio_processor = AudioConverterProcessor()

    pipeline = AudioAnalysisPipeline(
        stt_engine=stt_engine,
        diarizer=diarizer,
        audio_processor=audio_processor,
    )

    wav_bytes = create_synthetic_wav_bytes(duration_sec=2.0)
    utterances, language, overlap_summary = pipeline.process_bytes(wav_bytes)

    assert isinstance(utterances, list)
    assert len(utterances) > 0
    assert overlap_summary is not None
