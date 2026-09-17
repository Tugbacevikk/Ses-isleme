import os
import tempfile

from audio_analyzer.utils.audio_io import (
    create_synthetic_wav,
    get_audio_metadata,
    load_audio_bytes,
    save_audio_bytes,
)


def test_audio_io_synthetic_wav_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "test.wav")
        created_path = create_synthetic_wav(wav_path, duration_sec=1.0)
        assert os.path.exists(created_path)

        metadata = get_audio_metadata(created_path)
        assert metadata["sample_rate"] == 16000
        assert metadata["channels"] == 1
        assert abs(metadata["duration_sec"] - 1.0) < 0.1

        audio_bytes = load_audio_bytes(created_path)
        assert len(audio_bytes) > 0

        saved_path = os.path.join(tmpdir, "saved_copy.wav")
        save_audio_bytes(saved_path, audio_bytes)
        assert os.path.exists(saved_path)
