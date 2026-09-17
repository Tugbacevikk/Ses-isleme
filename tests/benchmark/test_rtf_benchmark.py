import os
import time
import pytest
from audio_analyzer.utils.audio_io import create_synthetic_wav, get_audio_metadata
from audio_analyzer.adapters.audio.rust_dsp_adapter import RustAudioDSPProcessor


def test_rtf_audio_dsp_benchmark(tmp_path):
    """
    Real-Time Factor (RTF) Performans Benchmark Testi.
    RTF = İşleme Süresi / Ses Süresi.
    RTF < 1.0 olması sesin gerçek zamandan daha hızlı işlendiğini doğrular.
    """
    sample_path = str(tmp_path / "benchmark_sample.wav")
    duration = 5.0  # 5 saniyelik test sesi
    create_synthetic_wav(sample_path, duration_sec=duration)

    metadata = get_audio_metadata(sample_path)
    assert metadata["duration_sec"] > 0

    dsp = RustAudioDSPProcessor()
    dummy_signal = [0.01 * (i % 100) for i in range(16000 * int(duration))]

    start_time = time.perf_counter()
    resampled = dsp.fast_resample(dummy_signal, original_sr=16000)
    vad_flags = dsp.fast_vad_energy(dummy_signal, frame_size=512, threshold=0.02)
    processing_time = time.perf_counter() - start_time

    rtf = processing_time / duration

    print(f"\n[BENCHMARK] Ses Süresi: {duration:.2f}s | İşleme Süresi: {processing_time:.4f}s | RTF: {rtf:.4f}")

    assert len(resampled) == len(dummy_signal)
    assert len(vad_flags) > 0
    assert rtf < 1.0, f"RTF performansı 1.0 altında olmalıdır (Ölçülen: {rtf:.4f})"
