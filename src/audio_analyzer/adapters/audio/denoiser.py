import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
from audio_analyzer.domain.interfaces import IAudioDenoiser

logger = logging.getLogger(__name__)


class DeepFilterDenoiser(IAudioDenoiser):
    """
    DeepFilterNet tabanlı yerel gürültü temizleme adaptörü.
    Arka plandaki cızırtı, ortam ve klavye seslerini temizler.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._df_model = None
        self._df_state = None
        self._initialized = False

    def _lazy_init(self):
        if not self._initialized and self.enabled:
            self._initialized = True
            try:
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
            audio, _ = load_audio(input_path, sr=self._df_state.sr())
            enhanced = enhance(self._df_model, self._df_state, audio)
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            save_audio(output_path, enhanced, self._df_state.sr())
            logger.info("Temizlenmiş ses dosyası kaydedildi: %s", output_path)
            return output_path
        except Exception as ex:
            logger.error("Denoise işlemi sırasında hata oluştu (%s). Ham ses kullanılıyor.", ex)
            return input_path

    def denoise_array(self, audio_data: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """RAM üzerindeki NumPy ses dizisini (16kHz float32) 0-Disk I/O ile gürültüden arındırır."""
        if not self.enabled or audio_data is None or len(audio_data) == 0:
            return audio_data

        self._lazy_init()
        if not self.enabled or self._df_model is None:
            return audio_data

        try:
            import numpy as np
            import torch
            from df.enhance import enhance

            audio_tensor = torch.from_numpy(audio_data).float().unsqueeze(0)
            enhanced_tensor = enhance(self._df_model, self._df_state, audio_tensor)
            return enhanced_tensor.squeeze().cpu().numpy()
        except Exception as ex:
            logger.error("Denoise In-Memory işlemi sırasında hata oluştu (%s). Ham ses kullanılıyor.", ex)
            return audio_data

