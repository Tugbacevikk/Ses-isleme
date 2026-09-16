import logging
from typing import List, Optional
from audio_analyzer.domain.interfaces import IDiarizer
from audio_analyzer.domain.models import DiarizationSegment, DeviceConfig

logger = logging.getLogger(__name__)


class FallbackDiarizer(IDiarizer):
    """
    Birincil (Primary) Diarizer motoru hata verdiğinde (HF Token geçersizliği, GPU OOM vb.)
    otomatik olarak ikincil (Fallback) motoru devreye sokan ve hataları düzgünce loglayan kompozit adaptör.
    """

    def __init__(self, primary: IDiarizer, fallback: IDiarizer):
        self.primary = primary
        self.fallback = fallback

    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        try:
            return self.primary.diarize(audio_path)
        except Exception as primary_error:
            logger.warning(
                f"[DIARIZATION FALLBACK] Birincil Diarizer ({self.primary.__class__.__name__}) hatası: {primary_error}. "
                f"İkincil motor ({self.fallback.__class__.__name__}) devreye sokuluyor."
            )
            try:
                return self.fallback.diarize(audio_path)
            except Exception as fallback_error:
                logger.error(
                    f"[DIARIZATION HATA] İkincil Diarizer ({self.fallback.__class__.__name__}) de başarısız oldu: {fallback_error}"
                )
                raise fallback_error
