import io
import wave
import math
import struct
import pytest
from fastapi.testclient import TestClient
from audio_analyzer.api.main import app

client = TestClient(app)


def make_valid_wav_bytes() -> bytes:
    """Geçerli 16kHz Mono WAV baytları (1 saniyelik sinüs sinyali) üretir."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        samples = []
        for i in range(16000):
            t = float(i) / 16000
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * t))
            samples.append(struct.pack("<h", val))
        f.writeframes(b"".join(samples))
    return buf.getvalue()


@pytest.mark.unit
def test_api_root_endpoint():
    """Web Arayüzü (HTML) kök dizin kontrolünü doğrular."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Ses Analizi" in response.text


@pytest.mark.unit
def test_api_upload_and_status_flow(tmp_path):
    """POST /api/v1/analyze ve GET /api/v1/jobs/{id} REST akışını doğrular."""
    # 1. POST /api/v1/analyze
    valid_wav = make_valid_wav_bytes()
    files = {"file": ("test_api.wav", valid_wav, "audio/wav")}
    
    post_res = client.post("/api/v1/analyze", files=files)
    assert post_res.status_code == 202
    post_data = post_res.json()
    assert "job_id" in post_data
    job_id = post_data["job_id"]

    # 2. GET /api/v1/jobs/{job_id}
    get_res = client.get(f"/api/v1/jobs/{job_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["job_id"] == job_id
    assert get_data["status"] == "COMPLETED"
