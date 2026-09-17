import os
import subprocess
import wave
from pathlib import Path

from audio_analyzer.domain.interfaces import IAudioProcessor


class AudioConverterProcessor(IAudioProcessor):
    """
    MP3, FLAC, M4A, OGG vb. tüm ses formatlarını
    16kHz Mono PCM WAV formatına dönüştüren ses ön işleme motoru.

    Yedekleme Sırası:
    1. PyAV (`av` python paketi - dahili FFmpeg C-kod kütüphanesi)
    2. FFmpeg CLI Komutu (Sistemde `ffmpeg` varsa)
    3. Torchaudio / Soundfile
    """

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin

    def normalize_and_resample(
        self, input_path: str, output_path: str, target_sample_rate: int = 16000
    ) -> str:
        input_p = Path(input_path)
        output_p = Path(output_path)
        output_p.parent.mkdir(parents=True, exist_ok=True)

        # 1. Öncelik: SoundFile (Hızlı & Doğrudan diske 16kHz mono WAV yazar)
        try:
            return self._convert_with_soundfile(input_p, output_p, target_sample_rate)
        except Exception:
            pass

        # 2. Öncelik: PyAV
        try:
            return self._convert_with_pyav(input_p, output_p, target_sample_rate)
        except Exception:
            pass

        # 3. Öncelik: FFmpeg CLI
        try:
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(input_p),
                "-ar",
                str(target_sample_rate),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output_p),
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return str(output_p)
        except Exception:
            pass

        if input_p.suffix.lower() == ".wav" and input_p.resolve() == output_p.resolve():
            return str(input_p)
        raise RuntimeError(f"Ses dönüştürme başarısız oldu: {input_path}")

    def _convert_with_soundfile(
        self, input_p: Path, output_p: Path, target_sample_rate: int
    ) -> str:
        import scipy.signal
        import soundfile as sf

        data, sr = sf.read(str(input_p))
        if data.ndim > 1:
            data = np.mean(data, axis=1)

        if sr != target_sample_rate:
            num_samples = int(len(data) * target_sample_rate / sr)
            data = scipy.signal.resample(data, num_samples)

        # 16-bit PCM WAV olarak kaydet
        sf.write(str(output_p), data, target_sample_rate, subtype="PCM_16")
        return str(output_p)

    def _convert_with_pyav(self, input_p: Path, output_p: Path, target_sample_rate: int) -> str:
        import av
        import numpy as np

        container = av.open(str(input_p))
        audio_stream = next(s for s in container.streams if s.type == "audio")

        resampler = av.AudioResampler(format="s16", layout="mono", rate=target_sample_rate)
        all_pcm_bytes = bytearray()

        for frame in container.decode(audio_stream):
            resampled_frames = resampler.resample(frame)
            for r_frame in resampled_frames:
                all_pcm_bytes.extend(r_frame.to_ndarray().tobytes())

        for r_frame in resampler.resample(None):
            all_pcm_bytes.extend(r_frame.to_ndarray().tobytes())

        with wave.open(str(output_p), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(target_sample_rate)
            wav_file.writeframes(all_pcm_bytes)

        return str(output_p)
