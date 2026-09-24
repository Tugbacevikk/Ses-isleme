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
        # Uzun prompt'ların neden olduğu yönlendirme (bias) ve halüsinatif kelime uydurmayı önlemek için varsayılan None
        self.initial_prompt = initial_prompt
        self._model = None

    def _lazy_load_model(self):
        """Modeli ihtiyaç anında (lazy loading) RAM/VRAM'e yükler."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                default_threads = min(8, os.cpu_count() or 4)
                cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", str(default_threads)))
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
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
        batch_size = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
        vad_params = dict(min_silence_duration_ms=1000, speech_pad_ms=400)

        try:
            from faster_whisper import BatchedInferencePipeline
            batched_model = BatchedInferencePipeline(model=self._model)
            segments, info = batched_model.transcribe(
                audio_path,
                batch_size=batch_size,
                language="tr",
                initial_prompt=self.initial_prompt or "Türkçe konuşma kaydı.",
                word_timestamps=True,
                beam_size=beam_size,
                condition_on_previous_text=False,
                temperature=0.0,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                no_speech_threshold=0.8,
                compression_ratio_threshold=2.4,
                log_prob_threshold=None,
                vad_filter=True,
                vad_parameters=vad_params,
            )
        except Exception as e:
            segments, info = self._model.transcribe(
                audio_path,
                language="tr",
                initial_prompt=self.initial_prompt or "Türkçe konuşma kaydı.",
                word_timestamps=True,
                beam_size=beam_size,
                condition_on_previous_text=False,
                temperature=0.0,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                no_speech_threshold=0.8,
                compression_ratio_threshold=2.4,
                log_prob_threshold=None,
                vad_filter=False,
            )

        words: List[WordSegment] = []
        last_clean_words: List[str] = []

        for segment in segments:
            if hasattr(segment, "words") and segment.words:
                for w in segment.words:
                    clean_w = w.word.strip().lower()
                    # Ardışık 3'ten fazla kelime tekrarı döngüsünü filtrele
                    if len(last_clean_words) >= 2 and clean_w == last_clean_words[-1] == last_clean_words[-2]:
                        continue
                    last_clean_words.append(clean_w)
                    if len(last_clean_words) > 10:
                        last_clean_words.pop(0)

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
