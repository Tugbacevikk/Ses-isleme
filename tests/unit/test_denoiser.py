from audio_analyzer.adapters.audio.denoiser import DeepFilterDenoiser


def test_denoiser_disabled_fallback():
    denoiser = DeepFilterDenoiser(enabled=False)
    input_path = "storage/raw/test.wav"
    output_path = "storage/raw/test.denoised.wav"

    res = denoiser.denoise(input_path, output_path)
    assert res == input_path


def test_denoiser_enabled_interface():
    denoiser = DeepFilterDenoiser(enabled=True)
    assert hasattr(denoiser, "denoise")
