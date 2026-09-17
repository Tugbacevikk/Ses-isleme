import pytest

try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
from audio_analyzer.domain.models import DeviceConfig


@pytest.mark.unit
def test_device_config_automatic_detection():
    """GPU varlığına göre cihaz tipini otomatik algıladığını doğrular."""
    config = DeviceConfig()
    if HAS_TORCH and torch.cuda.is_available():
        assert config.device == "cuda"
        assert config.compute_type == "float16"
    else:
        assert config.device == "cpu"
        assert config.compute_type == "int8"


@pytest.mark.unit
def test_device_config_explicit_override():
    """Donanım ayarlarının manuel ezilebildiğini (override) doğrular."""
    config = DeviceConfig(device="cpu", compute_type="int8", device_index=1)
    assert config.device == "cpu"
    assert config.compute_type == "int8"
    assert config.device_index == 1
