import os
import sys
from pathlib import Path

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

MODEL_DIR = Path(__file__).parent.parent / "storage" / "models"


def download_stt_model(model_size: str = "small"):
    """FasterWhisper modelini yerel depolama klasörüne indirir ve hazırlar."""
    stt_dir = MODEL_DIR / "stt" / model_size
    stt_dir.mkdir(parents=True, exist_ok=True)
    print(f"[STT] STT Modeli indiriliyor/kontrol ediliyor ({model_size}) -> {stt_dir}")

    try:
        from faster_whisper import WhisperModel

        # Modeli bir kez yerel klasöre indir
        model = WhisperModel(model_size, download_root=str(stt_dir), device="cpu", compute_type="int8")
        print(f"[OK] STT Modeli ({model_size}) yerel klasöre indirildi!")
    except Exception as e:
        print(f"[ERROR] STT Model indirme hatası: {e}")


def download_vad_model():
    """Silero VAD modelini yerel klasöre indirir ve önbelleğe alır."""
    vad_dir = MODEL_DIR / "vad"
    vad_dir.mkdir(parents=True, exist_ok=True)
    print(f"[VAD] Silero VAD Modeli indiriliyor -> {vad_dir}")

    try:
        import torch

        torch.hub.set_dir(str(vad_dir))
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        print("[OK] Silero VAD Modeli yerel klasöre kaydedildi!")
    except Exception as e:
        print(f"[WARNING] Silero VAD indirme uyarısı: {e}")


def download_diarization_model():
    """SpeechBrain ECAPA-TDNN konuşmacı ayrıştırma modelini yerel depolama klasörüne indirir."""
    print("[MODEL] SpeechBrain ECAPA-TDNN Modeli indiriliyor/kontrol ediliyor...")

    try:
        from speechbrain.inference.speaker import EncoderClassifier

        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
        )
        print("[OK] SpeechBrain ECAPA-TDNN Modeli yerel önbelleğe kaydedildi!")
    except Exception as e:
        print(f"[WARNING] Standard SpeechBrain indirme uyarısı: {e}")


if __name__ == "__main__":
    print("[START] Çevrimdışı Yapay Zeka Model İndirme Başlatılıyor...")
    download_stt_model("small")
    download_vad_model()
    download_diarization_model()
    print("[DONE] Çevrimdışı model paketleme tamamlandı!")
