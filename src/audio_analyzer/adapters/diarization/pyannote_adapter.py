from typing import List, Optional
from audio_analyzer.domain.interfaces import IDiarizer
from audio_analyzer.domain.models import DiarizationSegment, DeviceConfig


class PyAnnoteAdapter(IDiarizer):
    """
    PyAnnote.audio Speaker Diarization Motor Adaptörü.
    Donanım bilincine (DeviceConfig) sahiptir.
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

    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        try:
            self._lazy_load_pipeline()
            diarization = self._pipeline(audio_path)
            segments: List[DiarizationSegment] = []

            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(
                        speaker_id=str(speaker),
                        start_time=float(turn.start),
                        end_time=float(turn.end),
                    )
                )

            return segments
        except Exception as e:
            print(f"PyAnnoteAdapter error: {e}. Fallback to SpeechBrainECAPADiarizer.")
            from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer
            return SpeechBrainECAPADiarizer(device_config=self.device_config).diarize(audio_path)
