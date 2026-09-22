from typing import List, Optional, Tuple

from audio_analyzer.domain.interfaces import ISTTEngine
from audio_analyzer.domain.models import DeviceConfig, WordSegment


import os

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
            "Bu ses kaydı Türkçe bir konuşmadır. Yöresel konuşma şiveleri veya aksanlar içerse dahi "
            "lütfen kelimeleri en uygun Türkçe anlamlı kelimelere ve imla kurallarına uygun çevirin."
        )
        self._model = None

    def _lazy_load_model(self):
        """Modeli ihtiyaç anında (lazy loading) RAM/VRAM'e yükler."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", "4"))
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device_config.device,
                    compute_type=self.device_config.compute_type,
                    device_index=self.device_config.device_index,
                    cpu_threads=cpu_threads,
                )
            except ImportError:
                raise ImportError(
                    "faster-whisper kütüphanesi yüklü değil. 'pip install faster-whisper' çalıştırın."
                )

    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        self._lazy_load_model()
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "2"))

        try:
            segments, info = self._model.transcribe(
                audio_path,
                language="tr",
                initial_prompt=self.initial_prompt,
                word_timestamps=True,
                beam_size=beam_size,
                condition_on_previous_text=False,
                temperature=0.0,
                repetition_penalty=1.1,
                no_speech_threshold=0.6,
                vad_filter=True,
            )
        except Exception:
            segments, info = self._model.transcribe(
                audio_path,
                language="tr",
                initial_prompt=self.initial_prompt,
                word_timestamps=True,
                beam_size=beam_size,
                condition_on_previous_text=False,
                temperature=0.0,
                repetition_penalty=1.1,
                no_speech_threshold=0.6,
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
