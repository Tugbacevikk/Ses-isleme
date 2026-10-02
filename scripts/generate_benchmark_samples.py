import math
import struct
import wave
from pathlib import Path


def generate_wav(output_path: Path, duration_sec: float, sample_rate: int = 16000):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(sample_rate * duration_sec)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        samples = []
        for i in range(num_samples):
            t = float(i) / sample_rate
            # 0.5s segment alternation between 300Hz and 500Hz to simulate speaker speech
            freq = 300.0 if (int(t * 2) % 2 == 0) else 500.0
            sample = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * t))
            samples.append(struct.pack("<h", sample))
        wav_file.writeframes(b"".join(samples))


if __name__ == "__main__":
    base_dir = Path("storage/benchmark_samples")
    generate_wav(base_dir / "sample_10s.wav", 10.0)
    generate_wav(base_dir / "sample_30s.wav", 30.0)
    generate_wav(base_dir / "sample_60s.wav", 60.0)
    print("Benchmark sample audio files generated successfully.")
