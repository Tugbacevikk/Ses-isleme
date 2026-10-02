from unittest.mock import MagicMock

import numpy as np
import pytest

from audio_analyzer.config import reset_settings
from audio_analyzer.domain.models import WordSegment
from audio_analyzer.services.pipeline import AudioAnalysisPipeline


@pytest.fixture
def mock_components():
    stt = MagicMock()
    stt.transcribe.return_value = ([WordSegment(word="test", start_time=0.0, end_time=0.5)], "tr")
    stt.has_vad_filter = True

    diar = MagicMock()
    diar.diarize.return_value = []

    return stt, diar


def test_short_audio_skips_diarization_sequential(mock_components, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROFILE", "feedback")
    monkeypatch.setenv("PIPELINE_MIN_DIARIZE_SEC", "2.0")
    monkeypatch.setenv("RUN_PIPELINE_SEQUENTIALLY", "true")
    reset_settings()

    stt, diar = mock_components
    pipeline = AudioAnalysisPipeline(stt_engine=stt, diarizer=diar)

    # 1 second audio at 16kHz
    audio_array = np.zeros(16000, dtype=np.float32)

    _utterances, _lang, _overlap = pipeline._execute_pipeline(audio_array, audio_duration=1.0)

    stt.transcribe.assert_called_once()
    diar.diarize.assert_not_called()


def test_short_audio_skips_diarization_parallel(mock_components, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROFILE", "feedback")
    monkeypatch.setenv("PIPELINE_MIN_DIARIZE_SEC", "2.0")
    monkeypatch.setenv("RUN_PIPELINE_SEQUENTIALLY", "false")
    reset_settings()

    stt, diar = mock_components
    pipeline = AudioAnalysisPipeline(stt_engine=stt, diarizer=diar)

    # 1 second audio at 16kHz
    audio_array = np.zeros(16000, dtype=np.float32)

    _utterances, _lang, _overlap = pipeline._execute_pipeline(audio_array, audio_duration=1.0)

    stt.transcribe.assert_called_once()
    diar.diarize.assert_not_called()


def test_sufficient_audio_runs_diarization(mock_components, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROFILE", "feedback")
    monkeypatch.setenv("PIPELINE_MIN_DIARIZE_SEC", "2.0")
    monkeypatch.setenv("RUN_PIPELINE_SEQUENTIALLY", "false")
    reset_settings()

    stt, diar = mock_components
    pipeline = AudioAnalysisPipeline(stt_engine=stt, diarizer=diar)

    # 3 seconds audio
    audio_array = np.zeros(48000, dtype=np.float32)

    _utterances, _lang, _overlap = pipeline._execute_pipeline(audio_array, audio_duration=3.0)

    stt.transcribe.assert_called_once()
    diar.diarize.assert_called_once()
