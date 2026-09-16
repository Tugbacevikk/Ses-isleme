import pytest
from audio_analyzer.adapters.audio.rust_dsp_adapter import RustAudioDSPProcessor


@pytest.mark.unit
def test_rust_dsp_processor_resampling():
    """Rust / NumPy Resampling fonksiyonunun doğru çalıştığını doğrular."""
    dsp = RustAudioDSPProcessor()
    
    # 32kHz'lik basit bir sinyal
    data_32k = [0.0, 0.5, 1.0, 0.5, 0.0, -0.5, -1.0, -0.5]
    
    # 16kHz'e düşür (Örnek sayısı yarıya inmeli)
    resampled = dsp.fast_resample(data_32k, original_sr=32000)
    assert len(resampled) == 4


@pytest.mark.unit
def test_rust_dsp_processor_vad_energy():
    """Rust / NumPy VAD enerji algılamasının çalıştığını doğrular."""
    dsp = RustAudioDSPProcessor()
    
    # Sessiz kare vs Sesli kare
    silent_frame = [0.001] * 512
    loud_frame = [0.5] * 512
    signal = silent_frame + loud_frame

    vad_results = dsp.fast_vad_energy(signal, frame_size=512, threshold=0.02)
    assert len(vad_results) == 2
    assert vad_results[0] is False  # Sessiz
    assert vad_results[1] is True   # Sesli


@pytest.mark.unit
def test_rust_dsp_processor_cosine_similarity():
    """Rust / NumPy Kosinüs Benzerliği fonksiyonunu doğrular."""
    dsp = RustAudioDSPProcessor()
    
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0] # Aynı vektör -> Benzerlik 1.0
    vec_c = [0.0, 1.0, 0.0] # Dik vektör -> Benzerlik 0.0

    sim_same = dsp.fast_cosine_similarity(vec_a, vec_b)
    sim_diff = dsp.fast_cosine_similarity(vec_a, vec_c)

    assert abs(sim_same - 1.0) < 1e-4
    assert abs(sim_diff - 0.0) < 1e-4
