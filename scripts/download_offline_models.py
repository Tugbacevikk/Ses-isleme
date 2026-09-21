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
    print(f"📦 STT Modeli indiriliyor/kontrol ediliyor ({model_size}) -> {stt_dir}")

    try:
        from faster_whisper import WhisperModel

        # Modeli bir kez yerel klasöre indir
        model = WhisperModel(model_size, download_root=str(stt_dir), device="cpu", compute_type="int8")
        print(f"✅ STT Modeli ({model_size}) yerel klasöre indirildi!")
    except Exception as e:
        print(f"❌ STT Model indirme hatası: {e}")


def download_vad_model():
    """Silero VAD modelini yerel klasöre indirir ve önbelleğe alır."""
    vad_dir = MODEL_DIR / "vad"
    vad_dir.mkdir(parents=True, exist_ok=True)
    print(f"📦 Silero VAD Modeli indiriliyor -> {vad_dir}")

    try:
        import torch

        torch.hub.set_dir(str(vad_dir))
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        print("✅ Silero VAD Modeli yerel klasöre kaydedildi!")
    except Exception as e:
        print(f"⚠️ Silero VAD indirme uyarısı: {e}")


if __name__ == "__main__":
    print("🚀 Çevrimdışı (Air-Gapped) Yapay Zeka Model İndirme Başlatılıyor...")
    download_stt_model("small")
    download_vad_model()
    print("🎉 Çevrimdışı model paketleme tamamlandı!")
