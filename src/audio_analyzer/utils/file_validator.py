import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_valid_audio_content(file_bytes: bytes, filename: Optional[str] = None) -> bool:
    """
    Yüklenen dosya baytlarının gerçek ve bozulmamış bir ses dosyası (WAV, MP3, FLAC, OGG, M4A)
    içeriği taşıyıp taşımadığını sihirli baytlar (magic numbers) ve ses çözücü (audio decoder)
    kütüphaneleri vasıtasıyla doğrular.

    Sadece dosya uzantısına güvenmek güvenlik açığı (MIME Spoofing / Malicious File Upload)
    oluşturacağı için içerik doğrulaması zorunludur.
    """
    if not file_bytes or len(file_bytes) < 12:
        return False

    prefix_4 = file_bytes[:4]
    prefix_3 = file_bytes[:3]

    # 1. WAV: RIFF...WAVE
    if prefix_4 == b"RIFF" and file_bytes[8:12] == b"WAVE":
        return True

    # 2. MP3: ID3 etiketi veya MPEG Sync Frame
    if prefix_3 == b"ID3" or prefix_4[:2] in (b"\xff\xfb", b"\xff\xf2", b"\xff\xf3", b"\xff\xe3"):
        return True

    # 3. FLAC: fLaC
    if prefix_4 == b"fLaC":
        return True

    # 4. OGG: OggS
    if prefix_4 == b"OggS":
        return True

    # 5. M4A / MP4 Container: ftyp at bytes 4..7
    if file_bytes[4:8] == b"ftyp":
        return True

    # 6. İkincil Doğrulama (Secondary Fallback Inspection): PySoundFile / Wave kütüphaneleri
    try:
        import soundfile as sf

        with sf.SoundFile(io.BytesIO(file_bytes)) as f:
            if f.samplerate > 0 and f.channels > 0:
                return True
    except Exception:
        pass

    try:
        import wave

        with wave.open(io.BytesIO(file_bytes), "rb") as w:
            if w.getnchannels() > 0 and w.getframerate() > 0:
                return True
    except Exception:
        pass

    return False
