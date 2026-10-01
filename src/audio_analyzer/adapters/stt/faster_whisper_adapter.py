from typing import List, Optional, Tuple

from audio_analyzer.domain.interfaces import ISTTEngine
from audio_analyzer.domain.models import DeviceConfig, WordSegment


import os

import logging
from audio_analyzer.utils.cpu_budget import setup_cpu_thread_budget

logger = logging.getLogger(__name__)


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
        self.initial_prompt = initial_prompt
        self._model = None
        self._batched_model = None

    def _lazy_load_model(self):
        """Modeli ve BatchedInferencePipeline'ı ihtiyaç anında (lazy loading) bir kez yükler."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                cpu_threads = min(4, setup_cpu_thread_budget())
                try:
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device_config.device,
                        compute_type=self.device_config.compute_type,
                        device_index=self.device_config.device_index,
                        cpu_threads=cpu_threads,
                    )
                except Exception as first_err:
                    if "mkl_malloc" in str(first_err).lower() or "memory" in str(first_err).lower():
                        logger.warning("WhisperModel 1. yükleme uyarısı (%s), daha hafif model 'small' / cpu_threads=1 ile tekrar deneniyor.", first_err)
                        try:
                            self._model = WhisperModel(
                                "small",
                                device=self.device_config.device,
                                compute_type=self.device_config.compute_type,
                                device_index=self.device_config.device_index,
                                cpu_threads=1,
                            )
                        except Exception as second_err:
                            logger.warning("WhisperModel small yükleme uyarısı (%s), 'tiny' (int8) modeline düşülüyor.", second_err)
                            self._model = WhisperModel(
                                "tiny",
                                device=self.device_config.device,
                                compute_type="int8",
                                device_index=self.device_config.device_index,
                                cpu_threads=1,
                            )
                    else:
                        raise first_err

                try:
                    from faster_whisper import BatchedInferencePipeline

                    self._batched_model = BatchedInferencePipeline(model=self._model)
                    logger.info("FasterWhisper BatchedInferencePipeline tek seferlik oluşturuldu.")
                except Exception as b_err:
                    logger.info("BatchedInferencePipeline oluşturulamadı (%s), standart modele düşülüyor.", b_err)
                    self._batched_model = None

            except ImportError:
                raise ImportError(
                    "faster-whisper kütüphanesi yüklü değil. 'pip install faster-whisper' çalıştırın."
                )

    def transcribe(self, audio_path: str) -> Tuple[List[WordSegment], Optional[str]]:
        self._lazy_load_model()
        language = os.getenv("WHISPER_LANGUAGE", "tr")
        profile = os.getenv("PIPELINE_PROFILE", "full").lower()
        default_beam = "1" if profile == "feedback" else "5"
        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", default_beam))
        batch_size = int(os.getenv("WHISPER_BATCH_SIZE", "16"))
        vad_params = dict(min_silence_duration_ms=1000, speech_pad_ms=400)

        prompt_str = self.initial_prompt or (
            "Bu kayıt Türkçe dilinde net bir ses görüşmesidir. Lütfen kelimeleri doğru Türkçe karakterler (ç, ğ, ı, ö, ş, ü) ve noktalama işaretleriyle yazınız."
            if language == "tr"
            else None
        )

        if self._batched_model is not None:
            segments, info = self._batched_model.transcribe(
                audio_path,
                batch_size=batch_size,
                language=language,
                initial_prompt=prompt_str,
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
        else:
            segments, info = self._model.transcribe(
                audio_path,
                language=language,
                initial_prompt=prompt_str,
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
