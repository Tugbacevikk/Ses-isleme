import logging
from pathlib import Path
from typing import List, Optional, Tuple

from audio_analyzer.domain.interfaces import IAudioProcessor, IDiarizer, ISTTEngine, IVADProcessor
from audio_analyzer.domain.models import TranscriptUtterance
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.semantic_refiner import SemanticRefiner

logger = logging.getLogger(__name__)


class AudioAnalysisPipeline:
    """
    Ses Analizi Ana Pipeline Orkestratörü.
    Gelen ses dosyasını (MP3, WAV, FLAC vb.) normalize eder, VAD, STT ve Diarization
    motorlarını çalıştırıp çıktıları FusionEngine ve SemanticRefiner ile hizalar.
    """

    def __init__(
        self,
        stt_engine: ISTTEngine,
        diarizer: IDiarizer,
        audio_processor: Optional[IAudioProcessor] = None,
        vad_processor: Optional[IVADProcessor] = None,
        fusion_engine: Optional[FusionEngine] = None,
        semantic_refiner: Optional[SemanticRefiner] = None,
    ):
        self.stt_engine = stt_engine
        self.diarizer = diarizer
        self.audio_processor = audio_processor
        self.vad_processor = vad_processor
        self.fusion_engine = fusion_engine or FusionEngine()
        self.semantic_refiner = semantic_refiner or SemanticRefiner()

    def process(self, audio_path: str) -> Tuple[List[TranscriptUtterance], Optional[str]]:
        """
        Ses dosyasını (MP3/WAV/FLAC vb.) analiz eder.
        Returns: (List[TranscriptUtterance], detected_language)
        """
        working_path = audio_path
        created_temp_file: Optional[str] = None

        try:
            # 1. Ses Ön İşleme & Normalizasyon (MP3 -> 16kHz Mono WAV Dönüşümü)
            if self.audio_processor:
                processed_wav_path = str(Path(audio_path).with_suffix(".processed.wav"))
                working_path = self.audio_processor.normalize_and_resample(
                    input_path=audio_path,
                    output_path=processed_wav_path,
                    target_sample_rate=16000,
                )
                if working_path != audio_path:
                    created_temp_file = working_path

            # 2. VAD ile konuşma ve sessizlik aralıklarını çıkarma
            speech_timestamps: Optional[List[Tuple[float, float]]] = None
            if self.vad_processor:
                try:
                    speech_timestamps = self.vad_processor.get_speech_timestamps(working_path)
                except Exception as e:
                    logger.warning("VAD İşleme Hatası: %s. VAD filtresi atlanıyor.", e)

            # 3. STT ile kelime seviyesi metin çıkarma ve dil tespiti
            words, detected_language = self.stt_engine.transcribe(working_path)

            # 3b. VAD Filtrelemesi: Sessizlik alanlarında türetilen STT halüsinasyonlarını temizle
            if speech_timestamps and words:
                words = self._filter_words_with_vad(words, speech_timestamps)

            # 4. Derin konuşmacı zaman aralıkları çıkarma
            diarization_segments = self.diarizer.diarize(working_path)

            # 5. FusionEngine ile hizalama
            raw_utterances = self.fusion_engine.align(words, diarization_segments)

            # 6. SemanticRefiner ile anlamsal rol hizalaması
            final_utterances = self.semantic_refiner.refine(raw_utterances)

            return final_utterances, detected_language
        finally:
            if created_temp_file and Path(created_temp_file).exists():
                try:
                    Path(created_temp_file).unlink()
                except Exception as cleanup_err:
                    logger.warning("Geçici ses dosyası temizleme uyarısı: %s", cleanup_err)

    def _filter_words_with_vad(
        self, words: List, speech_timestamps: List[Tuple[float, float]], tolerance: float = 0.3
    ) -> List:
        """
        VAD konuşma aralıklarının tamamen dışında kalan (sessizlikte türetilmiş)
        STT kelime halüsinasyonlarını eler.
        """
        if not speech_timestamps:
            return words

        filtered_words = []
        for word in words:
            # Kelimenin orta noktası veya aralığı herhangi bir VAD konuşma segmentine düşüyor mu?
            is_speech = any(
                (start - tolerance) <= word.midpoint <= (end + tolerance)
                for start, end in speech_timestamps
            )
            if is_speech:
                filtered_words.append(word)

        return filtered_words
