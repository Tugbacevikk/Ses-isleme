from typing import List, Tuple

import numpy as np

from audio_analyzer.adapters.audio.audio_converter import AudioConverterProcessor
from audio_analyzer.domain.interfaces import IAudioProcessor

# Rust PyO3 Modülünü Dinamik Olarak İçe Aktarmayı Dene
try:
    import native_audio_dsp

    HAS_RUST_NATIVE = True
except ImportError:
    HAS_RUST_NATIVE = False


class RustAudioDSPProcessor(IAudioProcessor):
    """
    Python & Rust Hibrit Ses Ön İşleme ve Performans Adaptörü.
    Rust C-extension derlenmişse PyO3 üzerinden Rust'ın 0-latency C hızındaki
    fonksiyonlarını kullanır; aksi halde NumPy fallback ile kesintisiz çalışır.
    """

    def __init__(self, fallback_processor: IAudioProcessor = None):
        self.fallback = fallback_processor or AudioConverterProcessor()
        self.using_rust = HAS_RUST_NATIVE

    def normalize_and_resample(
        self, input_path: str, output_path: str, target_sample_rate: int = 16000
    ) -> str:
        """
        Girdi sesini varsayılan AudioConverterProcessor ile 16kHz WAV'a çevirir.
        """
        return self.fallback.normalize_and_resample(input_path, output_path, target_sample_rate)

    def fast_resample(self, pcm_signal: List[float], original_sr: int) -> List[float]:
        """
        Rust hızında PCM sinyal resample işlemi.
        """
        if HAS_RUST_NATIVE:
            return native_audio_dsp.resample_pcm_16k(pcm_signal, original_sr)
        else:
            # NumPy Fallback
            if original_sr == 16000:
                return pcm_signal
            arr = np.array(pcm_signal, dtype=np.float32)
            num_samples = int(len(arr) * 16000 / original_sr)
            resampled = np.interp(
                np.linspace(0, len(arr), num_samples, endpoint=False), np.arange(len(arr)), arr
            )
            return resampled.tolist()

    def fast_vad_energy(
        self, pcm_signal: List[float], frame_size: int = 512, threshold: float = 0.02
    ) -> List[bool]:
        """
        Rust hızında Voice Activity Detection (VAD) RMS enerji tespiti.
        """
        if HAS_RUST_NATIVE:
            return native_audio_dsp.calculate_signal_energy_vad(pcm_signal, frame_size, threshold)
        else:
            # NumPy Fallback
            arr = np.array(pcm_signal, dtype=np.float32)
            num_frames = len(arr) // frame_size
            results = []
            for i in range(num_frames):
                frame = arr[i * frame_size : (i + 1) * frame_size]
                rms = np.sqrt(np.mean(frame**2))
                results.append(bool(rms >= threshold))
            return results

    def fast_cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """
        Rust hızında Konuşmacı Vektörü Kosinüs Benzerliği.
        """
        if HAS_RUST_NATIVE:
            return native_audio_dsp.compute_cosine_similarity(vec_a, vec_b)
        else:
            # NumPy Fallback
            a = np.array(vec_a, dtype=np.float32)
            b = np.array(vec_b, dtype=np.float32)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))
