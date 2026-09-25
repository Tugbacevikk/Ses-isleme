import logging
import os
from typing import Optional

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
from audio_analyzer.adapters.audio.audio_converter import AudioConverterProcessor
from audio_analyzer.adapters.audio.silero_vad import SileroVADProcessor
from audio_analyzer.domain.models import DeviceConfig
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.services.semantic_refiner import SemanticRefiner

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_cached_pipeline: Optional[AudioAnalysisPipeline] = None


def reset_pipeline_cache():
    """Önbellekteki pipeline nesnesini sıfırlar, böylece güncel parametreler yeniden yüklenir."""
    global _cached_pipeline
    _cached_pipeline = None


def get_shared_pipeline() -> AudioAnalysisPipeline:
    """
    Sıcak Yükleme (Warm-Loading) Singleton Fabrikası.
    Ağır GPU/CPU yapay zeka modellerini (Whisper, SpeechBrain/PyAnnote) disk/bellekten
    yalnızca İLK İSTEKTE yükler ve sonraki tüm analiz görevlerinde hazır modeli yeniden kullanır.
    Her istekte modeli sıfırdan yükleme gecikmesini (10-30sn) ortadan kaldırır.
    """
    global _cached_pipeline
    if _cached_pipeline is not None:
        return _cached_pipeline

    device_config = DeviceConfig()

    # Ortam değişkenlerinden blueprint parametrelerini oku (Hızlı ve dengeli analiz için 'small')
    whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "small")
    max_silence_threshold = float(os.getenv("MAX_SILENCE_THRESHOLD", "1.5"))

    # 1. STT Engine (FasterWhisper)
    try:
        from audio_analyzer.adapters.stt.faster_whisper_adapter import FasterWhisperAdapter

        stt_engine = FasterWhisperAdapter(
            model_size=whisper_model_size, device_config=device_config
        )
    except Exception as e:
        raise RuntimeError(
            f"STT Motoru (FasterWhisper) başlatılamadı: {e}. Lütfen model bağımlılıklarını kontrol edin."
        )


    # 2. Diarization Engine (%100 Yerel ve İnternetsiz Token-Free Diarizasyon)
    from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer

    diarizer = SpeechBrainECAPADiarizer(device_config=device_config)

    from audio_analyzer.adapters.audio.rust_dsp_adapter import RustAudioDSPProcessor
    from audio_analyzer.adapters.audio.denoiser import DeepFilterDenoiser

    audio_processor = RustAudioDSPProcessor()
    vad_processor = SileroVADProcessor()
    enable_denoiser = os.getenv("ENABLE_DENOISER", "true").lower() == "true"
    denoiser = DeepFilterDenoiser(enabled=enable_denoiser)

    _cached_pipeline = AudioAnalysisPipeline(
        stt_engine=stt_engine,
        diarizer=diarizer,
        audio_processor=audio_processor,
        vad_processor=vad_processor,
        denoiser=denoiser,
        fusion_engine=FusionEngine(max_silence_threshold=max_silence_threshold),
        semantic_refiner=SemanticRefiner(),
    )
    return _cached_pipeline
