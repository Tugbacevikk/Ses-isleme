import logging
import math
import os

import numpy as np
import scipy.signal

from audio_analyzer.domain.interfaces import IAudioDenoiser

logger = logging.getLogger(__name__)


class DeepFilterDenoiser(IAudioDenoiser):
    """
    DeepFilterNet tabanlı yerel gürültü temizleme adaptörü.
    Arka plandaki cızırtı, ortam ve klavye seslerini temizler.
    DeepFilterNet dahili olarak 48kHz ses işlediğinden 16kHz ses verileri 48kHz'e
    yükseltilir (upsample) ve işlem sonrası tekrar 16kHz'e düşürülür (downsample).
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._df_model = None
        self._df_state = None
        self._initialized = False

    def _lazy_init(self):
        if not self._initialized and self.enabled:
            self._initialized = True
            try:
                import sys
                import types
                import torchaudio

                if "torchaudio.backend.common" not in sys.modules:
                    b = sys.modules.get("torchaudio.backend") or types.ModuleType("torchaudio.backend")
                    bc = types.ModuleType("torchaudio.backend.common")
                    setattr(bc, "AudioMetaData", getattr(torchaudio, "AudioMetaData", None))
                    setattr(b, "common", bc)
                    sys.modules["torchaudio.backend"] = b
                    sys.modules["torchaudio.backend.common"] = bc

                from df.enhance import init_df

                self._df_model, self._df_state, _ = init_df()
                logger.info("DeepFilterNet denoiser başarıyla yüklendi.")
            except Exception as e:
                logger.warning(
                    "DeepFilterNet başlatılamadı (%s). Gürültü filtresi bypass edilecek.", e
                )
                self.enabled = False

    def denoise(self, input_path: str, output_path: str) -> str:
        if not self.enabled:
            return input_path

        self._lazy_init()
        if not self.enabled or self._df_model is None:
            return input_path

        try:
            from df.enhance import enhance, load_audio, save_audio

            logger.info("Ses dosyası gürültü temizleme işlemine alınıyor: %s", input_path)
            target_sr = self._df_state.sr() if self._df_state else 48000
            audio, sr = load_audio(input_path, sr=target_sr)
            enhanced = enhance(self._df_model, self._df_state, audio)
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            save_audio(output_path, enhanced, target_sr)
            logger.info("Temizlenmiş ses dosyası kaydedildi: %s", output_path)
            return output_path
        except Exception as ex:
            logger.error("Denoise işlemi sırasında hata oluştu (%s). Ham ses kullanılıyor.", ex)
            return input_path

    def denoise_array(self, audio_data: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """RAM üzerindeki NumPy ses dizisini (16kHz float32) 48kHz'e resample edip gürültüden arındırır."""
        if not self.enabled or audio_data is None or len(audio_data) == 0:
            return audio_data

        self._lazy_init()
        if not self.enabled or self._df_model is None:
            return audio_data

        try:
            import torch
            from df.enhance import enhance

            target_sr = self._df_state.sr() if self._df_state else 48000
            
            # 16kHz -> 48kHz Resampling (eğer farklıysa)
            if sample_rate != target_sr:
                gcd_val = math.gcd(int(sample_rate), target_sr)
                audio_resampled = scipy.signal.resample_poly(
                    audio_data, target_sr // gcd_val, int(sample_rate) // gcd_val
                )
            else:
                audio_resampled = audio_data

            audio_tensor = torch.from_numpy(audio_resampled).float().unsqueeze(0)
            enhanced_tensor = enhance(self._df_model, self._df_state, audio_tensor)
            enhanced_array = enhanced_tensor.squeeze().cpu().numpy()

            # 48kHz -> 16kHz (Orijinal hıza geri dönüş)
            if sample_rate != target_sr:
                gcd_val = math.gcd(int(sample_rate), target_sr)
                enhanced_array = scipy.signal.resample_poly(
                    enhanced_array, int(sample_rate) // gcd_val, target_sr // gcd_val
                )

            return enhanced_array
        except Exception as ex:
            logger.error("Denoise In-Memory işlemi sırasında hata oluştu (%s). Ham ses kullanılıyor.", ex)
            return audio_data

