import logging
from pathlib import Path
from typing import List, Optional, Tuple

from audio_analyzer.domain.interfaces import IAudioDenoiser, IAudioProcessor, IDiarizer, ISTTEngine, IVADProcessor
from audio_analyzer.domain.models import OverlapSummary, TranscriptUtterance
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.overlap_detector import OverlapDetector
from audio_analyzer.services.semantic_refiner import SemanticRefiner

logger = logging.getLogger(__name__)


class AudioAnalysisPipeline:
    """
    Ses Analizi Ana Pipeline Orkestratörü.
    Gelen ses dosyasını (MP3, WAV, FLAC vb.) gürültüden arındırır (Denoiser),
    normalize eder, VAD, STT ve Diarization motorlarını paralel çalıştırır,
    çakışmaları (Overlap Detection) tespit eder ve çıktıları FusionEngine ile birleştirir.
    """

    def __init__(
        self,
        stt_engine: ISTTEngine,
        diarizer: IDiarizer,
        audio_processor: Optional[IAudioProcessor] = None,
        vad_processor: Optional[IVADProcessor] = None,
        denoiser: Optional[IAudioDenoiser] = None,
        fusion_engine: Optional[FusionEngine] = None,
        semantic_refiner: Optional[SemanticRefiner] = None,
    ):
        self.stt_engine = stt_engine
        self.diarizer = diarizer
        self.audio_processor = audio_processor
        self.vad_processor = vad_processor
        self.denoiser = denoiser
        self.fusion_engine = fusion_engine or FusionEngine()
        self.semantic_refiner = semantic_refiner or SemanticRefiner()

    def process(
        self, audio_path: str
    ) -> Tuple[List[TranscriptUtterance], Optional[str], OverlapSummary]:
        """
        Ses dosyasını (MP3/WAV/FLAC vb.) analiz eder.
        Returns: (List[TranscriptUtterance], detected_language, overlap_summary)
        """
        working_path = audio_path
        created_temp_files: List[str] = []

        try:
            # 1. Ön Gürültü Temizleme (DeepFilterNet Denoiser)
            if self.denoiser:
                denoised_wav_path = str(Path(audio_path).with_suffix(".denoised.wav"))
                audio_after_denoise = self.denoiser.denoise(
                    input_path=audio_path, output_path=denoised_wav_path
                )
                if audio_after_denoise != audio_path:
                    created_temp_files.append(audio_after_denoise)
                    working_path = audio_after_denoise

            # 2. Ses Ön İşleme & Normalizasyon (MP3 -> 16kHz Mono WAV Dönüşümü)
            if self.audio_processor:
                processed_wav_path = str(Path(working_path).with_suffix(".processed.wav"))
                working_path = self.audio_processor.normalize_and_resample(
                    input_path=working_path,
                    output_path=processed_wav_path,
                    target_sample_rate=16000,
                )
                if working_path != audio_path and working_path not in created_temp_files:
                    created_temp_files.append(working_path)

            # 3. VAD ile konuşma ve sessizlik aralıklarını çıkarma
            speech_timestamps: Optional[List[Tuple[float, float]]] = None
            if self.vad_processor:
                try:
                    speech_timestamps = self.vad_processor.get_speech_timestamps(working_path)
                except Exception as e:
                    logger.warning("VAD İşleme Hatası: %s. VAD filtresi atlanıyor.", e)

            # 4 & 5. STT ve Diarization Motorlarını PARALEL (Eşzamanlı) Çalıştır
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_stt = executor.submit(self.stt_engine.transcribe, working_path)
                future_diar = executor.submit(self.diarizer.diarize, working_path)

                words, detected_language = future_stt.result()
                diarization_segments = future_diar.result()

            # 4b. VAD Filtrelemesi: Sessizlik alanlarında türetilen STT halüsinasyonlarını temizle
            if speech_timestamps and words:
                words = self._filter_words_with_vad(words, speech_timestamps)

            # 6. Konuşma Çakışması (Overlap Detection) Metriklerini Hesapla
            total_duration = 0.0
            if words:
                total_duration = max(w.end_time for w in words)
            elif diarization_segments:
                total_duration = max(s.end_time for s in diarization_segments)

            overlap_summary = OverlapDetector.detect_overlaps(
                diarization_segments=diarization_segments, total_audio_duration=total_duration
            )

            # 7. FusionEngine ile hizalama
            raw_utterances = self.fusion_engine.align(words, diarization_segments)

            # 8. SemanticRefiner ile anlamsal rol hizalaması
            final_utterances = self.semantic_refiner.refine(raw_utterances)

            return final_utterances, detected_language, overlap_summary
        finally:
            for tmp_file in created_temp_files:
                if Path(tmp_file).exists():
                    try:
                        Path(tmp_file).unlink()
                    except Exception as cleanup_err:
                        logger.warning("Geçici ses dosyası temizleme uyarısı: %s", cleanup_err)

    def process_bytes(
        self, file_bytes: bytes
    ) -> Tuple[List[TranscriptUtterance], Optional[str], OverlapSummary]:
        """
        0-Disk I/O: Ses dosyasını doğrudan RAM bellek (In-Memory Stream Buffer) üzerinden işler.
        Diske 0 bayt geçici ses dosyası yazılır.
        """
        import io
        import numpy as np

        # 1. Ses Baytlarını RAM'de 16kHz Mono float32 NumPy dizisine çevir
        if self.audio_processor and hasattr(self.audio_processor, "convert_bytes_to_ndarray"):
            audio_array, _ = self.audio_processor.convert_bytes_to_ndarray(
                file_bytes, target_sample_rate=16000
            )
        else:
            import soundfile as sf

            audio_array, sr = sf.read(io.BytesIO(file_bytes))
            if audio_array.ndim > 1:
                audio_array = np.mean(audio_array, axis=1)

        # 2. Ön Gürültü Temizleme (RAM Üzerinde Denoise)
        if self.denoiser and hasattr(self.denoiser, "denoise_array"):
            audio_array = self.denoiser.denoise_array(audio_array, sample_rate=16000)

        # 3. VAD ile konuşma aralıkları (RAM Üzerinde)
        speech_timestamps: Optional[List[Tuple[float, float]]] = None
        if self.vad_processor:
            try:
                speech_timestamps = self.vad_processor.get_speech_timestamps(audio_array)
            except Exception as e:
                logger.warning("VAD In-Memory İşleme Hatası: %s. VAD filtresi atlanıyor.", e)

        # 4 & 5. STT ve Diarization Motorlarını PARALEL (RAM tamponundan) Çalıştır
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_stt = executor.submit(self.stt_engine.transcribe, audio_array)
            future_diar = executor.submit(self.diarizer.diarize, audio_array)

            words, detected_language = future_stt.result()
            diarization_segments = future_diar.result()

        # 4b. VAD Filtrelemesi
        if speech_timestamps and words:
            words = self._filter_words_with_vad(words, speech_timestamps)

        # 6. Konuşma Çakışması Metrikleri
        total_duration = 0.0
        if words:
            total_duration = max(w.end_time for w in words)
        elif diarization_segments:
            total_duration = max(s.end_time for s in diarization_segments)

        overlap_summary = OverlapDetector.detect_overlaps(
            diarization_segments=diarization_segments, total_audio_duration=total_duration
        )

        # 7. FusionEngine
        raw_utterances = self.fusion_engine.align(words, diarization_segments)

        # 8. SemanticRefiner
        final_utterances = self.semantic_refiner.refine(raw_utterances)

        return final_utterances, detected_language, overlap_summary

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
            is_speech = any(
                (start - tolerance) <= word.midpoint <= (end + tolerance)
                for start, end in speech_timestamps
            )
            if is_speech:
                filtered_words.append(word)

        return filtered_words
