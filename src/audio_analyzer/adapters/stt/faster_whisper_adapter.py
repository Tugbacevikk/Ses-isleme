from typing import List, Optional, Tuple
from audio_analyzer.domain.interfaces import ISTTEngine
from audio_analyzer.domain.models import WordSegment, DeviceConfig


class FasterWhisperAdapter(ISTTEngine):
    """
    Faster-Whisper (CTranslate2) Speech-to-Text Motor Adaptörü.
    Donanım bilincine (DeviceConfig) sahiptir: GPU'da CUDA+float16, CPU'da int8 modunda çalışır.
    """

    def __init__(
        self,
        model_size: str = "small",
        device_config: Optional[DeviceConfig] = None,
        initial_prompt: Optional[str] = None,
    ):
        self.model_size = model_size
        self.device_config = device_config or DeviceConfig()
        self.initial_prompt = initial_prompt or (
            "Bu bir Türkçe ses kaydıdır. İmla kurallarına, kelime hecelemelerine, "
            "noktalama işaretlerine ve düzgün Türkçe dil bilgisine dikkat ediniz."
        )
        self._model = None

    def _lazy_load_model(self):
        """Modeli ihtiyaç anında (lazy loading) RAM/VRAM'e yükler."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device_config.device,
                    compute_type=self.device_config.compute_type,
                    device_index=self.device_config.device_index,
                )
            except ImportError:
                raise ImportError(
                    "faster-whisper kütüphanesi yüklü değil. 'pip install faster-whisper' çalıştırın."
                )

    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        self._lazy_load_model()
        
        try:
            segments, info = self._model.transcribe(
                audio_path,
                language="tr",
                initial_prompt=self.initial_prompt,
                word_timestamps=True,
                beam_size=5,
                vad_filter=True,
            )
        except Exception:
            segments, info = self._model.transcribe(
                audio_path,
                language="tr",
                initial_prompt=self.initial_prompt,
                word_timestamps=True,
                beam_size=5,
                vad_filter=False,
            )

        words: List[WordSegment] = []
        for segment in segments:
            if hasattr(segment, "words") and segment.words:
                for w in segment.words:
                    words.append(
                        WordSegment(
                            word=w.word,
                            start_time=w.start,
                            end_time=w.end,
                            probability=w.probability if hasattr(w, "probability") else 1.0,
                        )
                    )

        detected_language = info.language if info and hasattr(info, "language") else None
        return words, detected_language
