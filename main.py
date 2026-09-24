import sys
from pathlib import Path

# Proje kök dizinindeki src klasörünü sys.path'e otomatik ekler
sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn

if __name__ == "__main__":
    print("🚀 Ses Analizi Platformu Başlatılıyor (http://127.0.0.1:8000)...")
    uvicorn.run("audio_analyzer.main:app", host="127.0.0.1", port=8000, reload=True, app_dir="src")
