import hashlib
import hmac
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from audio_analyzer.api.routers.jobs import verify_api_key
from audio_analyzer.api.main import lifespan, app, get_cors_config
from audio_analyzer.utils.ssrf_validator import validate_callback_url
from audio_analyzer.services.webhook_service import WebhookService
from audio_analyzer.api.rate_limiter import RedisRateLimiter

@pytest.mark.asyncio
async def test_startup_fails_in_production_without_api_key():
    with patch.dict("os.environ", {"APP_ENV": "production", "API_KEY": "", "WEBHOOK_SECRET": "sec123"}):
        with pytest.raises(ValueError) as excinfo:
            async with lifespan(app):
                pass
        assert "API_KEY" in str(excinfo.value)

@pytest.mark.asyncio
async def test_startup_fails_in_production_without_webhook_secret():
    with patch.dict("os.environ", {"APP_ENV": "production", "API_KEY": "key123", "WEBHOOK_SECRET": ""}):
        with pytest.raises(ValueError) as excinfo:
            async with lifespan(app):
                pass
        assert "WEBHOOK_SECRET" in str(excinfo.value)

@pytest.mark.asyncio
async def test_verify_api_key_blocks_when_key_invalid():
    with patch.dict("os.environ", {"API_KEY": "secret123"}):
        with pytest.raises(HTTPException) as excinfo:
            await verify_api_key(api_key="wrongkey")
        assert excinfo.value.status_code == 401

def test_cors_wildcard_disables_credentials():
    origins, allow_creds = get_cors_config("*")
    assert origins == ["*"]
    assert allow_creds is False, "Wildcard '*' origin varken allow_credentials False olmalı!"

def test_ssrf_validator_rejects_internal_and_reserved_urls():
    with patch.dict("os.environ", {"APP_ENV": "production"}):
        assert validate_callback_url("http://127.0.0.1/webhook") is False
        assert validate_callback_url("http://169.254.169.254/latest/meta-data") is False
        assert validate_callback_url("http://localhost/webhook") is False
        assert validate_callback_url("http://db:5432/webhook") is False
        assert validate_callback_url("http://example.com/webhook") is False  # http in production

    with patch.dict("os.environ", {"APP_ENV": "production"}), \
         patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        assert validate_callback_url("https://example.com/webhook") is True   # https in production

def test_ssrf_validator_whitelist_check():
    with patch.dict("os.environ", {"APP_ENV": "production", "WEBHOOK_ALLOWED_HOSTS": "allowed-api.example.com"}), \
         patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
        assert validate_callback_url("https://other-api.example.com/webhook") is False
        assert validate_callback_url("https://allowed-api.example.com/webhook") is True

def test_webhook_signature_generation():
    svc = WebhookService(secret_key="my_secret_key")
    timestamp = "1775130000"
    body = '{"job_id":"123","status":"COMPLETED"}'
    sig = svc.generate_signature(timestamp, body)
    
    assert sig.startswith("sha256=")
    expected_data = f"{timestamp}.{body}".encode("utf-8")
    expected_hash = hmac.new("my_secret_key".encode("utf-8"), expected_data, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected_hash}"

@pytest.mark.asyncio
async def test_rate_limiter_hashes_api_key():
    limiter = RedisRateLimiter(rate_limit=10, period_sec=60)
    mock_redis = MagicMock()
    mock_redis.eval = MagicMock(return_value=1)
    
    with patch.object(limiter, "_get_redis", return_value=mock_redis):
        raw_key = "super_secret_api_key_12345"
        allowed, rem, reset = await limiter.is_allowed(key=raw_key)
        assert allowed is True
        
        # Verify raw API key was NOT passed to Redis EVAL
        eval_args = mock_redis.eval.call_args[0]
        redis_key_passed = eval_args[2]
        assert raw_key not in redis_key_passed
        assert redis_key_passed.startswith("rate:key_hash:")
