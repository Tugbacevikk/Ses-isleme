import pytest

from audio_analyzer.adapters.diarization.cluster_diarizer import LocalSpectralClusterDiarizer


@pytest.mark.unit
def test_local_spectral_cluster_diarizer_fallback():
    """Token gerektirmeyen yerel akustik kümeleme motorunun çalıştığını doğrular."""
    diarizer = LocalSpectralClusterDiarizer()
    assert diarizer.num_speakers == 2
