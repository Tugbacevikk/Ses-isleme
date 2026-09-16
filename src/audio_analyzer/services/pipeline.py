from typing import List, Tuple, Optional
from pathlib import Path
from audio_analyzer.domain.interfaces import ISTTEngine, IDiarizer, IAudioProcessor, IVADProcessor
from audio_analyzer.domain.models import TranscriptUtterance
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.semantic_refiner import SemanticRefiner


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

        # 1. Ses Ön İşleme & Normalizasyon (MP3 -> 16kHz Mono WAV Dönüşümü)
        if self.audio_processor:
            processed_wav_path = str(Path(audio_path).with_suffix(".processed.wav"))
            working_path = self.audio_processor.normalize_and_resample(
                input_path=audio_path,
                output_path=processed_wav_path,
                target_sample_rate=16000,
            )

        # 2. VAD ile konuşma ve sessizlik aralıklarını çıkarma
        if self.vad_processor:
            _ = self.vad_processor.get_speech_timestamps(working_path)

        # 3. STT ile kelime seviyesi metin çıkarma ve dil tespiti
        words, detected_language = self.stt_engine.transcribe(working_path)

        # 4. Derin konuşmacı zaman aralıkları çıkarma
        diarization_segments = self.diarizer.diarize(working_path)

        # 5. FusionEngine ile hizalama
        raw_utterances = self.fusion_engine.align(words, diarization_segments)

        # 6. SemanticRefiner ile anlamsal rol hizalaması
        final_utterances = self.semantic_refiner.refine(raw_utterances)

        return final_utterances, detected_language
