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

logger = logging.getLogger(__name__)

_cached_pipeline: Optional[AudioAnalysisPipeline] = None


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

    # Ortam değişkenlerinden blueprint parametrelerini oku
    whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "medium")
    max_silence_threshold = float(os.getenv("MAX_SILENCE_THRESHOLD", "1.5"))

    # 1. STT Engine (FasterWhisper)
    try:
        from audio_analyzer.adapters.stt.faster_whisper_adapter import FasterWhisperAdapter

        stt_engine = FasterWhisperAdapter(
            model_size=whisper_model_size, device_config=device_config
        )
    except Exception as e:
        allow_mock = os.getenv("ALLOW_MOCK_STT", "false").lower() == "true"
        if allow_mock:
            logger.warning(
                "FasterWhisper yüklenemedi (%s). ALLOW_MOCK_STT=true olduğu için MockSTTAdapter kullanılıyor.",
                e,
            )
            from audio_analyzer.adapters.stt.mock_stt_adapter import MockSTTAdapter

            stt_engine = MockSTTAdapter()
        else:
            raise RuntimeError(
                f"STT Motoru (FasterWhisper) başlatılamadı: {e}. Lütfen model bağımlılıklarını kontrol edin."
            )

    # 2. Diarization Engine (PyAnnote + SpeechBrain Fallback Chain)
    hf_token = os.getenv("HF_TOKEN")
    from audio_analyzer.adapters.diarization.fallback_diarizer import FallbackDiarizer
    from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer

    speechbrain_diarizer = SpeechBrainECAPADiarizer(device_config=device_config)

    if hf_token:
        try:
            from audio_analyzer.adapters.diarization.pyannote_adapter import PyAnnoteAdapter

            primary_pyannote = PyAnnoteAdapter(auth_token=hf_token, device_config=device_config)
            diarizer = FallbackDiarizer(primary=primary_pyannote, fallback=speechbrain_diarizer)
        except Exception as e:
            logger.warning("PyAnnoteAdapter yüklenemedi: %s. Doğrudan SpeechBrain kullanılıyor.", e)
            diarizer = speechbrain_diarizer
    else:
        diarizer = speechbrain_diarizer

    from audio_analyzer.adapters.audio.rust_dsp_adapter import RustAudioDSPProcessor

    audio_processor = RustAudioDSPProcessor()
    vad_processor = SileroVADProcessor()

    _cached_pipeline = AudioAnalysisPipeline(
        stt_engine=stt_engine,
        diarizer=diarizer,
        audio_processor=audio_processor,
        vad_processor=vad_processor,
        fusion_engine=FusionEngine(max_silence_threshold=max_silence_threshold),
        semantic_refiner=SemanticRefiner(),
    )
    return _cached_pipeline
