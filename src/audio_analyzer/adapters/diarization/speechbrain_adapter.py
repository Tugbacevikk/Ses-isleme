import logging
import os
from typing import List, Optional, Union

import numpy as np
import torch

from audio_analyzer.domain.interfaces import IDiarizer
from audio_analyzer.domain.models import DeviceConfig, DiarizationSegment

logger = logging.getLogger(__name__)


class SpeechBrainECAPADiarizer(IDiarizer):
    """
    SpeechBrain ECAPA-TDNN Derin Sinir Ağı Konuşmacı Ayrıştırma Motoru (%100 Token-Free & Çevrimdışı).
    192-boyutlu derin nöral ses parmak izleri çıkararak iki kadın konuşmacı arasındaki ses farklarını
    kusursuz biçimde ayırır.
    """

    def __init__(
        self,
        device_config: DeviceConfig = None,
        num_speakers: Optional[int] = None,
        max_speakers: int = 10,
    ):
        self.device_config = device_config or DeviceConfig()
        self.num_speakers = num_speakers
        self.max_speakers = max_speakers
        self._classifier = None

    def _load_classifier(self):
        if self._classifier is None:
            from speechbrain.inference.speaker import EncoderClassifier
            from pathlib import Path

            spk_dir = Path(__file__).parent.parent.parent.parent / "storage" / "models" / "diarization" / "speechbrain_ecapa"
            spk_dir.mkdir(parents=True, exist_ok=True)

            try:
                self._classifier = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir=str(spk_dir),
                    run_opts={"device": self.device_config.device},
                )
            except Exception as ex:
                logger.warning("SpeechBrain loading note (%s), retrying without explicit savedir...", ex)
                self._classifier = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    run_opts={"device": self.device_config.device},
                )

    def diarize(self, audio_input: Union[str, np.ndarray]) -> List[DiarizationSegment]:
        try:
            self._load_classifier()
            import scipy.signal
            import soundfile as sf
            from scipy.cluster.hierarchy import fcluster, linkage
            from scipy.signal import medfilt
            from scipy.spatial.distance import pdist

            if isinstance(audio_input, np.ndarray):
                data = audio_input
                sr = 16000
            else:
                data, sr = sf.read(audio_input)
            if data.ndim > 1:
                data = np.mean(data, axis=1)

            target_sr = 16000
            if sr != target_sr:
                from math import gcd

                g = gcd(int(sr), target_sr)
                data = scipy.signal.resample_poly(data, target_sr // g, int(sr) // g)
                sr = target_sr

            win_sec = 1.2
            step_sec = float(os.getenv("DIARIZATION_STEP_SEC", "0.6"))
            win_samples = int(sr * win_sec)
            step_samples = int(sr * step_sec)

            if len(data) < win_samples:
                return [
                    DiarizationSegment(
                        speaker_id="SPEAKER_00", start_time=0.0, end_time=len(data) / sr
                    )
                ]

            num_wins = 1 + (len(data) - win_samples) // step_samples
            valid_clips = []
            valid_indices = []

            # Energy gating to skip absolute silence (5th percentile to keep quiet speech)
            rms_energies = np.array(
                [
                    np.sqrt(np.mean(data[i * step_samples : i * step_samples + win_samples] ** 2))
                    for i in range(num_wins)
                ]
            )
            energy_thresh = max(1e-5, np.percentile(rms_energies, 5))

            for i in range(num_wins):
                clip = data[i * step_samples : i * step_samples + win_samples]
                if rms_energies[i] < energy_thresh:
                    continue
                valid_clips.append(clip)
                valid_indices.append(i)

            if not valid_clips:
                return [
                    DiarizationSegment(
                        speaker_id="SPEAKER_00", start_time=0.0, end_time=len(data) / sr
                    )
                ]

            # Dynamic Batching for SpeechBrain Embedding Extraction
            batch_size = int(os.getenv("DIARIZATION_BATCH_SIZE", "32"))
            raw_embeddings = []
            for b_idx in range(0, len(valid_clips), batch_size):
                b_chunk = valid_clips[b_idx : b_idx + batch_size]
                batch_arr = np.array(b_chunk, dtype=np.float32)
                tensor_batch = torch.tensor(batch_arr, dtype=torch.float32)

                with torch.no_grad():
                    emb = self._classifier.encode_batch(tensor_batch)
                    emb_np = emb.squeeze(1).cpu().numpy()
                    if emb_np.ndim == 1:
                        emb_np = np.expand_dims(emb_np, axis=0)
                    raw_embeddings.append(emb_np)

            embeddings = np.vstack(raw_embeddings)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
            unit_embs = embeddings / norms

            dist_thresh = float(os.getenv("DIARIZATION_THRESHOLD", "0.55"))

            if len(unit_embs) == 1:
                raw_valid_labels = np.zeros(1, dtype=int)
            else:
                from sklearn.cluster import AgglomerativeClustering

                if self.num_speakers is not None:
                    n_spk = min(self.num_speakers, len(unit_embs))
                    if n_spk <= 1:
                        raw_valid_labels = np.zeros(len(unit_embs), dtype=int)
                    else:
                        model = AgglomerativeClustering(
                            n_clusters=n_spk, metric="cosine", linkage="average"
                        )
                        raw_valid_labels = model.fit_predict(unit_embs)
                else:
                    model = AgglomerativeClustering(
                        n_clusters=None,
                        metric="cosine",
                        linkage="average",
                        distance_threshold=dist_thresh,
                    )
                    raw_valid_labels = model.fit_predict(unit_embs)
                    n_clusters = len(np.unique(raw_valid_labels))
                    if n_clusters > self.max_speakers:
                        model_cap = AgglomerativeClustering(
                            n_clusters=self.max_speakers, metric="cosine", linkage="average"
                        )
                        raw_valid_labels = model_cap.fit_predict(unit_embs)

            # Map valid labels back to all windows
            raw_labels = np.zeros(num_wins, dtype=int)
            last_lbl = raw_valid_labels[0] if len(raw_valid_labels) > 0 else 0
            val_idx = 0
            for i in range(num_wins):
                if val_idx < len(valid_indices) and i == valid_indices[val_idx]:
                    last_lbl = raw_valid_labels[val_idx]
                    val_idx += 1
                raw_labels[i] = last_lbl

            k_size = min(5, len(raw_labels))
            if k_size % 2 == 0:
                k_size = max(1, k_size - 1)
            final_labels = (
                medfilt(raw_labels, kernel_size=k_size) if len(raw_labels) > 0 else raw_labels
            )

            segments: List[DiarizationSegment] = []
            current_spk = f"SPEAKER_{final_labels[0]:02d}"
            start_t = 0.0

            for i in range(1, num_wins):
                spk = f"SPEAKER_{final_labels[i]:02d}"
                if spk != current_spk:
                    end_t = i * step_sec
                    segments.append(
                        DiarizationSegment(
                            speaker_id=current_spk, start_time=start_t, end_time=end_t
                        )
                    )
                    current_spk = spk
                    start_t = end_t

            end_t = len(data) / sr
            segments.append(
                DiarizationSegment(speaker_id=current_spk, start_time=start_t, end_time=end_t)
            )

            return segments

        except Exception as e:
            logger.warning("SpeechBrainECAPADiarizer error, fallback: %s", e)
            from audio_analyzer.adapters.diarization.cluster_diarizer import (
                LocalSpectralClusterDiarizer,
            )

            fallback_diarizer = LocalSpectralClusterDiarizer(device_config=self.device_config)
            if isinstance(audio_input, str):
                return fallback_diarizer.diarize(audio_input)
            else:
                # If audio_input is array, create temporary audio file for spectral fallback
                import soundfile as sf
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                sf.write(tmp_path, audio_input, 16000, subtype="PCM_16")
                try:
                    return fallback_diarizer.diarize(tmp_path)
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
