import logging
from typing import List, Optional
from audio_analyzer.domain.interfaces import IDiarizer
from audio_analyzer.domain.models import DiarizationSegment, DeviceConfig

logger = logging.getLogger(__name__)


class PyAnnoteAdapter(IDiarizer):
    """
    PyAnnote.audio Speaker Diarization Motor Adaptörü.
    Donanım bilincine (DeviceConfig) sahiptir.
    Hata oluştuğunda istisnayı fırlatır ve loglar; sessizce başka adaptör import etmez (Clean Architecture).
    """

    def __init__(
        self,
        auth_token: Optional[str] = None,
        device_config: Optional[DeviceConfig] = None,
        model_name: str = "pyannote/speaker-diarization-3.1",
    ):
        self.auth_token = auth_token
        self.device_config = device_config or DeviceConfig()
        self.model_name = model_name
        self._pipeline = None

    def _lazy_load_pipeline(self):
        if self._pipeline is None:
            try:
                import torch
                import warnings
                warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
                from pyannote.audio import Pipeline
                try:
                    self._pipeline = Pipeline.from_pretrained(
                        self.model_name,
                        token=self.auth_token,
                    )
                except TypeError:
                    self._pipeline = Pipeline.from_pretrained(
                        self.model_name,
                        use_auth_token=self.auth_token,
                    )
                if self.device_config.device == "cuda" and torch.cuda.is_available():
                    self._pipeline.to(torch.device("cuda"))
            except ImportError:
                raise ImportError(
                    "pyannote.audio kütüphanesi yüklü değil. 'pip install pyannote.audio' çalıştırın."
                )
            except Exception as e:
                logger.error(f"PyAnnote model yükleme hatası: {e}")
                raise RuntimeError(f"PyAnnote model yüklenemedi: {e}")

    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        try:
            self._lazy_load_pipeline()
            import torch
            import soundfile as sf

            # Soundfile ile sesi yukleyip PyAnnote'a waveform dict olarak vererek
            # Windows uzerindeki torchcodec / FFmpeg DLL yukleme hatalarini tamamen bypass ediyoruz.
            data, sr = sf.read(audio_path)
            if data.ndim > 1:
                data = data.mean(axis=1)
            waveform = torch.tensor(data, dtype=torch.float32).unsqueeze(0)
            audio_input = {"waveform": waveform, "sample_rate": sr}

            diarization = self._pipeline(audio_input)
            annotation = getattr(diarization, "speaker_diarization", diarization)
            segments: List[DiarizationSegment] = []

            for turn, _, speaker in annotation.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(
                        speaker_id=str(speaker),
                        start_time=float(turn.start),
                        end_time=float(turn.end),
                    )
                )

            return segments
        except Exception as e:
            logger.error(f"PyAnnote Diarization başarısız: {e}")
            raise RuntimeError(f"PyAnnote Diarization çalıştırılamadı: {e}")
