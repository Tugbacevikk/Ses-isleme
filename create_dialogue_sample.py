"""
2 Konuşmacılı Sentetik Test Ses Dosyası Üretici (create_dialogue_sample.py)
Bu betik, 2 farklı konuşmacının (Müşteri ve Temsilci) ses frekanslarını simüle eden 
6 saniyelik test ses dosyası üretir.
"""

import wave
import math
import struct
from pathlib import Path


def generate_dialogue_wav():
    output_path = Path("storage/raw/dialogue_sample.wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 16000
    
    # 0 - 3 sn: Konuşmacı 0 (Yüksek Ton - 440 Hz Sinüs Dalgası)
    # 3 - 6 sn: Konuşmacı 1 (Kalın Ton - 220 Hz Sinüs Dalgası)
    duration_total = 6.0
    num_samples = int(sample_rate * duration_total)

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)      # Mono
        wav_file.setsampwidth(2)      # 16-bit
        wav_file.setframerate(sample_rate)

        samples = []
        for i in range(num_samples):
            t = float(i) / sample_rate
            if t < 3.0:
                # Konuşmacı 0 (İnce ses frekansı)
                freq = 440.0
            else:
                # Konuşmacı 1 (Kalın ses frekansı)
                freq = 220.0

            sample = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * freq * t))
            samples.append(struct.pack("<h", sample))

        wav_file.writeframes(b"".join(samples))

    print(f"[+] 2 Konuşmacılı Sentetik Ses Dosyası Oluşturuldu: {output_path.absolute()}")


if __name__ == "__main__":
    generate_dialogue_wav()
