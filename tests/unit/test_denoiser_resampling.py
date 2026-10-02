import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from audio_analyzer.adapters.audio.denoiser import DeepFilterDenoiser
from audio_analyzer.config import get_settings, reset_settings


def test_denoiser_default_disabled():
    reset_settings()
    settings = get_settings()
    assert settings.enable_denoiser is False
    denoiser = DeepFilterDenoiser()
    assert denoiser.enabled is False


def test_denoiser_array_resampling_16k_to_48k():
    denoiser = DeepFilterDenoiser(enabled=True)
    denoiser._initialized = True
    denoiser._df_model = MagicMock()
    fake_state = MagicMock()
    fake_state.sr.return_value = 48000
    denoiser._df_state = fake_state

    # Input: 1 second of 16kHz sine wave
    t = np.linspace(0, 1, 16000, endpoint=False)
    audio_16k = np.sin(2 * np.pi * 440 * t).astype(np.float32)

    # Inject mock df.enhance module into sys.modules
    mock_df_enhance = MagicMock()
    import torch
    mock_df_enhance.enhance.side_effect = lambda model, state, tensor: torch.zeros((1, 48000), dtype=torch.float32)
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "df.enhance", mock_df_enhance)

        out_array = denoiser.denoise_array(audio_16k, sample_rate=16000)

        # Check that tensor passed to enhance had 48000 samples (upsampled from 16k)
        assert mock_df_enhance.enhance.called
        passed_tensor = mock_df_enhance.enhance.call_args[0][2]
        assert passed_tensor.shape[-1] == 48000

        # Check that output array was downsampled back to 16000 samples
        assert len(out_array) == 16000
