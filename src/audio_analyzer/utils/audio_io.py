import os
import wave
import math
import struct
from pathlib import Path
from typing import Dict, Any


def load_audio_bytes(file_path: str) -> bytes:
    """
    Belirtilen yoldan ses dosyasının ham byte verisini okur.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {file_path}")
    with open(path, "rb") as f:
        return f.read()


def save_audio_bytes(file_path: str, data: bytes) -> str:
    """
    Ses dosyası byte verisini diskte belirtilen yola yazar.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path.absolute())


def get_audio_metadata(file_path: str) -> Dict[str, Any]:
    """
    WAV ses dosyasının kanal sayısı, örnekleme hızı (sample rate) ve süresini (sn) döner.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Ses dosyası bulunamadı: {file_path}")

    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.getnframes()
            duration_sec = frames / float(sample_rate) if sample_rate > 0 else 0.0

            return {
                "channels": channels,
                "sample_rate": sample_rate,
                "frames": frames,
                "duration_sec": duration_sec,
                "format": "WAV"
            }
    except Exception:
        # WAV dışı formatlar (MP3/FLAC) için dosya boyutu tahmini
        file_size = path.stat().st_size
        return {
            "channels": 1,
            "sample_rate": 16000,
            "duration_sec": 0.0,
            "file_size_bytes": file_size,
            "format": path.suffix.replace(".", "").upper()
        }


def create_synthetic_wav(file_path: str, duration_sec: float = 3.0, freq: float = 440.0) -> str:
    """
    Testler için 16kHz Mono 16-bit sinüs dalgalı sentetik WAV dosyası üretir.
    """
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for i in range(num_samples):
            t = float(i) / sample_rate
            sample = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * t))
            data = struct.pack("<h", sample)
            wav_file.writeframesraw(data)

    return str(path.absolute())
