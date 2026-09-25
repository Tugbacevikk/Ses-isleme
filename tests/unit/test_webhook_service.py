import pytest
from audio_analyzer.services.webhook_service import WebhookService


@pytest.mark.unit
def test_webhook_signature_generation():
    service = WebhookService(secret_key="test_secret")
    payload = {"job_id": "123", "status": "COMPLETED"}
    import json

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sig = service.generate_signature(payload_bytes)
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA256 hex string length


@pytest.mark.unit
def test_webhook_send_callback_empty_url():
    import asyncio

    service = WebhookService(secret_key="test_secret")
    assert service.send_callback("", {}) is False
    assert asyncio.run(service.send_callback_async("", {})) is False
