import pytest
from fastapi.testclient import TestClient

from audio_analyzer.api.main import app
from audio_analyzer.utils.file_validator import is_valid_audio_content

client = TestClient(app)


def test_valid_audio_magic_headers():
    # WAV (RIFF...WAVE)
    wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    assert is_valid_audio_content(wav_bytes, "test.wav") is True

    # MP3 (ID3)
    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 10
    assert is_valid_audio_content(mp3_bytes, "test.mp3") is True

    # FLAC
    flac_bytes = b"fLaC\x00\x00\x00\x22" + b"\x00" * 10
    assert is_valid_audio_content(flac_bytes, "test.flac") is True

    # OGG
    ogg_bytes = b"OggS\x00\x02\x00\x00" + b"\x00" * 10
    assert is_valid_audio_content(ogg_bytes, "test.ogg") is True

    # M4A (ftyp at index 4)
    m4a_bytes = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00"
    assert is_valid_audio_content(m4a_bytes, "test.m4a") is True


def test_invalid_audio_content_rejected():
    # Plain text file disguised as wav
    text_bytes = b"This is a text file, not an audio file."
    assert is_valid_audio_content(text_bytes, "hacker.wav") is False

    # HTML document disguised as mp3
    html_bytes = b"<html><body><h1>Hacked</h1></body></html>"
    assert is_valid_audio_content(html_bytes, "malicious.mp3") is False

    # Too short bytes
    short_bytes = b"RIFF"
    assert is_valid_audio_content(short_bytes, "short.wav") is False


def test_upload_api_rejects_fake_audio_file():
    fake_wav_bytes = b"Hello world, I am a text file pretending to be wav!"
    files = {"file": ("fake.wav", fake_wav_bytes, "audio/wav")}

    response = client.post("/api/v1/analyze", files=files)
    assert response.status_code == 400
    assert "geçerli ve bozulmamış bir ses dosyası içeriği" in response.json()["detail"]
