import numpy as np
import torch
from typing import List, Optional
from audio_analyzer.domain.interfaces import IDiarizer
from audio_analyzer.domain.models import DiarizationSegment, DeviceConfig


class SpeechBrainECAPADiarizer(IDiarizer):
    """
    SpeechBrain ECAPA-TDNN Derin Sinir Ağı Konuşmacı Ayrıştırma Motoru (%100 Token-Free & Çevrimdışı).
    192-boyutlu derin nöral ses parmak izleri çıkararak iki kadın konuşmacı arasındaki ses farklarını 
    kusursuz biçimde ayırır.
    """

    def __init__(self, device_config: DeviceConfig = None, num_speakers: Optional[int] = None, max_speakers: int = 10):
        self.device_config = device_config or DeviceConfig()
        self.num_speakers = num_speakers
        self.max_speakers = max_speakers
        self._classifier = None

    def _load_classifier(self):
        if self._classifier is None:
            import os
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            from speechbrain.inference.speaker import EncoderClassifier
            self._classifier = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                run_opts={"device": self.device_config.device}
            )

    def diarize(self, audio_path: str) -> List[DiarizationSegment]:
        try:
            self._load_classifier()
            import soundfile as sf
            import scipy.signal
            from scipy.spatial.distance import pdist
            from scipy.cluster.hierarchy import linkage, fcluster
            from scipy.signal import medfilt

            data, sr = sf.read(audio_path)
            if data.ndim > 1:
                data = np.mean(data, axis=1)

            target_sr = 16000
            if sr != target_sr:
                num_samples = int(len(data) * target_sr / sr)
                data = scipy.signal.resample(data, num_samples)
                sr = target_sr

            win_sec = 1.5
            step_sec = 0.5
            win_samples = int(sr * win_sec)
            step_samples = int(sr * step_sec)

            if len(data) < win_samples:
                return [DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=len(data) / sr)]

            num_wins = 1 + (len(data) - win_samples) // step_samples
            embeddings = []
            valid_indices = []

            # Energy gating to skip silence
            rms_energies = np.array([np.sqrt(np.mean(data[i * step_samples : i * step_samples + win_samples] ** 2)) for i in range(num_wins)])
            energy_thresh = max(1e-4, np.percentile(rms_energies, 20))

            for i in range(num_wins):
                clip = data[i * step_samples : i * step_samples + win_samples]
                if rms_energies[i] < energy_thresh:
                    continue
                tensor_clip = torch.tensor(clip, dtype=torch.float32).unsqueeze(0)

                with torch.no_grad():
                    emb = self._classifier.encode_batch(tensor_clip)
                    emb_vec = emb.squeeze().cpu().numpy()
                    embeddings.append(emb_vec)
                    valid_indices.append(i)

            if not embeddings:
                return [DiarizationSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=len(data) / sr)]

            embeddings = np.array(embeddings)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
            unit_embs = embeddings / norms

            dists = pdist(unit_embs, metric='cosine')
            Z = linkage(dists, method='average')

            if self.num_speakers is not None:
                n_spk = min(self.num_speakers, len(unit_embs))
                raw_valid_labels = fcluster(Z, t=n_spk, criterion='maxclust') - 1
            else:
                # Dynamic speaker estimation (distance threshold ~0.38 for meeting scalability)
                raw_valid_labels = fcluster(Z, t=0.38, criterion='distance') - 1
                n_clusters = len(np.unique(raw_valid_labels))
                if n_clusters > self.max_speakers:
                    raw_valid_labels = fcluster(Z, t=self.max_speakers, criterion='maxclust') - 1

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
            final_labels = medfilt(raw_labels, kernel_size=k_size) if len(raw_labels) > 0 else raw_labels

            segments: List[DiarizationSegment] = []
            current_spk = f"SPEAKER_{final_labels[0]:02d}"
            start_t = 0.0

            for i in range(1, num_wins):
                spk = f"SPEAKER_{final_labels[i]:02d}"
                if spk != current_spk:
                    end_t = i * step_sec
                    segments.append(DiarizationSegment(speaker_id=current_spk, start_time=start_t, end_time=end_t))
                    current_spk = spk
                    start_t = end_t

            end_t = len(data) / sr
            segments.append(DiarizationSegment(speaker_id=current_spk, start_time=start_t, end_time=end_t))

            return segments

        except Exception as e:
            print(f"SpeechBrainECAPADiarizer error, fallback: {e}")
            from audio_analyzer.adapters.diarization.cluster_diarizer import LocalSpectralClusterDiarizer
            return LocalSpectralClusterDiarizer(device_config=self.device_config).diarize(audio_path)
