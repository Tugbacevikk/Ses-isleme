import logging
import types
from unittest.mock import MagicMock, patch

import numpy as np

from audio_analyzer.adapters.audio.silero_vad import SileroVADProcessor


def test_silero_vad_uses_package_get_speech_timestamps():
    processor = SileroVADProcessor(threshold=0.5)
    
    mock_module = types.ModuleType("silero_vad")
    dummy_model = MagicMock()
    mock_get_speech_timestamps = MagicMock(return_value=[{"start": 0, "end": 16000}])
    mock_load = MagicMock(return_value=dummy_model)
    
    mock_module.load_silero_vad = mock_load
    mock_module.get_speech_timestamps = mock_get_speech_timestamps
    
    with patch.dict("sys.modules", {"silero_vad": mock_module}):
        dummy_audio = np.zeros(16000, dtype=np.float32)
        timestamps = processor.get_speech_timestamps(dummy_audio, min_silence_duration_ms=400)
        
        mock_load.assert_called_once()
        mock_get_speech_timestamps.assert_called_once()
        assert timestamps == [(0.0, 1.0)]

def test_silero_vad_fallback_to_energy_when_package_fails(caplog):
    processor = SileroVADProcessor(threshold=0.5)
    
    with caplog.at_level(logging.WARNING):
        with patch.dict("sys.modules", {"silero_vad": None}):
            dummy_audio = np.zeros(16000, dtype=np.float32)
            timestamps = processor.get_speech_timestamps(dummy_audio, min_silence_duration_ms=400)
            
            # Energy fallback olmalı
            assert isinstance(timestamps, list)
            assert len(timestamps) > 0
            # WARNING seviyesinde loglanmalı
            assert any(record.levelno == logging.WARNING for record in caplog.records)
