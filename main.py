import os
import sys
from pathlib import Path

src_dir = str(Path(__file__).parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

os.environ["PYTHONPATH"] = src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")

from audio_analyzer.api.main import app
import uvicorn

if __name__ == "__main__":
    print("🚀 Ses Analizi Platformu Başlatılıyor (http://127.0.0.1:8000)...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
