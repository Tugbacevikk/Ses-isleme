import io
import math
import struct
import wave

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


@pytest.mark.unit
def test_utterance_crud_flow():
    """ITranscriptRepository üzerinden PUT, DELETE, POST utterance endpoint akışlarını doğrular."""
    valid_wav = make_valid_wav_bytes()
    files = {"file": ("test_crud.wav", valid_wav, "audio/wav")}
    post_res = client.post("/api/v1/analyze", files=files)
    job_id = post_res.json()["job_id"]

    # 1. POST /api/v1/jobs/{job_id}/utterances (Kutu Ekle)
    add_res = client.post(
        f"/api/v1/jobs/{job_id}/utterances",
        json={
            "speaker_id": "SPEAKER_00",
            "start_time": 0.0,
            "end_time": 1.0,
            "text": "Merhaba dunya",
        },
    )
    assert add_res.status_code == 200
    assert add_res.json()["status"] == "SUCCESS"

    # 2. PUT /api/v1/jobs/{job_id}/utterances/0 (Kutu Guncelle)
    update_res = client.put(
        f"/api/v1/jobs/{job_id}/utterances/0",
        json={"speaker_id": "SPEAKER_01", "text": "Guncellenmis metin"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "SUCCESS"

    # 3. DELETE /api/v1/jobs/{job_id}/utterances/0 (Kutu Sil)
    del_res = client.delete(f"/api/v1/jobs/{job_id}/utterances/0")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "SUCCESS"


@pytest.mark.unit
def test_list_jobs_endpoint():
    """GET /api/v1/jobs sayfalamalı geçmiş işler listeleme endpoint'ini doğrular."""
    list_res = client.get("/api/v1/jobs?skip=0&limit=10")
    assert list_res.status_code == 200
    jobs = list_res.json()
    assert isinstance(jobs, list)
    assert len(jobs) >= 1


@pytest.mark.unit
def test_api_key_authorization_on_read_and_write_endpoints(monkeypatch):
    """API_KEY ortam değişkeni ayarlandığında tüm okuma ve yazma endpoint'lerinin 401 döndürdüğünü doğrular."""
    monkeypatch.setenv("API_KEY", "secret-test-key")

    # 1. Okuma Endpoint'leri (GET)
    res_list = client.get("/api/v1/jobs")
    assert res_list.status_code == 401

    res_get = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert res_get.status_code == 401

    res_audio = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/audio")
    assert res_audio.status_code == 401

    # 2. Yanlış API Key ile erişim
    res_wrong = client.get("/api/v1/jobs", headers={"X-API-Key": "wrong-key"})
    assert res_wrong.status_code == 401

    # 3. Doğru API Key ile erişim
    res_valid = client.get("/api/v1/jobs", headers={"X-API-Key": "secret-test-key"})
    assert res_valid.status_code == 200
