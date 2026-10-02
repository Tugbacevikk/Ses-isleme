import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from audio_analyzer.adapters.diarization.speechbrain_adapter import (
    SpeechBrainECAPADiarizer,
    majority_vote_filter,
)


import pytest


def test_majority_vote_filter():
    labels = np.array([0, 2, 0, 1, 1, 1, 0])
    filtered = majority_vote_filter(labels, kernel_size=3)
    # The [0, 2, 0] window at index 1 -> majority is 0, so 2 becomes 0
    assert filtered[1] == 0

@pytest.mark.torch
def test_model_dir_env_variable():
    with patch.dict(os.environ, {"MODEL_DIR": "/custom/model/path"}):
        diarizer = SpeechBrainECAPADiarizer()
        with patch("speechbrain.inference.speaker.EncoderClassifier.from_hparams") as mock_hparams:
            mock_hparams.return_value = MagicMock()
            diarizer._load_classifier()
            savedir_arg = mock_hparams.call_args[1].get("savedir")
            assert str(Path("/custom/model/path/diarization/speechbrain_ecapa")) in savedir_arg
