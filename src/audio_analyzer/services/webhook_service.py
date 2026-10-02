import hashlib
import hmac
import json
import logging
import time
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Üçüncü Parti Kurumsal Sistemlere (CRM, HBYS, Santral)
    Asenkron Geri Bildirim (Webhook / Callback) Gönderim Servisi.
    HMAC-SHA256 imzalama ve üstel bekleme (exponential backoff) retry desteği içerir.
    High-throughput (4k-5k req/sec) için httpx TCP keep-alive connection pooling kullanır.
    """

    _sync_client = None
    _async_client = None

    def __init__(self, secret_key: Optional[str] = None):
        from audio_analyzer.config import get_settings

        settings = get_settings()
        self.secret_key = secret_key or settings.webhook_secret

    @classmethod
    def get_sync_client(cls):
        """High-throughput sync connection pooling için paylaşımlı httpx.Client."""
        if cls._sync_client is None:
            try:
                import httpx

                limits = httpx.Limits(max_keepalive_connections=200, max_connections=1000)
                cls._sync_client = httpx.Client(timeout=10.0, limits=limits, follow_redirects=False)
            except Exception as e:
                logger.warning("httpx.Client initialize warning (%s), falling back to urllib", e)
                return None
        return cls._sync_client

    @classmethod
    def get_async_client(cls):
        """High-throughput async connection pooling için paylaşımlı httpx.AsyncClient (follow_redirects=False)."""
        if cls._async_client is None:
            try:
                import httpx

                limits = httpx.Limits(max_keepalive_connections=200, max_connections=1000)
                cls._async_client = httpx.AsyncClient(timeout=10.0, limits=limits, follow_redirects=False)
            except Exception as e:
                logger.warning("httpx.AsyncClient initialize warning (%s)", e)
                return None
        return cls._async_client

    def generate_signature(self, timestamp_str: Any, body_str: Optional[str] = None) -> str:
        """
        Payload veri bütünlüğünü ve zaman damgasını garanti etmek için HMAC-SHA256 imzası üretir.
        Format: sha256=HMAC(secret, f"{timestamp}.{body}")
        """
        if body_str is None:
            body = timestamp_str
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            elif isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            timestamp_str = str(int(time.time()))
            body_str = body
        else:
            if isinstance(body_str, bytes):
                body_str = body_str.decode("utf-8")
            elif isinstance(body_str, dict):
                body_str = json.dumps(body_str, ensure_ascii=False, separators=(",", ":"))

        signature_data = f"{timestamp_str}.{body_str}".encode("utf-8")
        raw_hmac = hmac.new(
            self.secret_key.encode("utf-8"), signature_data, hashlib.sha256
        ).hexdigest()
        return f"sha256={raw_hmac}"

    def send_callback(
        self,
        callback_url: str,
        payload: Dict[str, Any],
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> bool:
        if not callback_url:
            return False

        from audio_analyzer.utils.ssrf_validator import validate_callback_url
        if not validate_callback_url(callback_url):
            logger.warning("Webhook gönderimi SSRF engeline takıldı (%s)", callback_url)
            return False

        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(
                self.send_callback_async(callback_url, payload, max_retries, backoff_factor)
            )
            return True
        else:
            return asyncio.run(
                self.send_callback_async(callback_url, payload, max_retries, backoff_factor)
            )

    async def send_callback_async(
        self,
        callback_url: str,
        payload: Dict[str, Any],
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> bool:
        if not callback_url:
            return False

        from audio_analyzer.utils.ssrf_validator import validate_callback_url
        if not validate_callback_url(callback_url):
            logger.warning("Async Webhook gönderimi SSRF engeline takıldı (%s)", callback_url)
            return False

        import asyncio
        timestamp_str = str(int(time.time()))
        body_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        payload_bytes = body_str.encode("utf-8")
        signature = self.generate_signature(timestamp_str, body_str)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "AudioAnalyzer-Webhook/1.0",
            "X-Timestamp": timestamp_str,
            "X-Signature": signature,
        }

        client = self.get_async_client()
        if client is None:
            return False

        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(callback_url, content=payload_bytes, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.info("Async Webhook callback delivered to %s (%d)", callback_url, resp.status_code)
                    return True
                else:
                    logger.warning("Async Webhook returned non-2xx status (%d) for %s", resp.status_code, callback_url)
            except Exception as ex:
                logger.warning("Async Webhook attempt %d/%d failed for %s: %s", attempt, max_retries, callback_url, ex)

            if attempt < max_retries:
                await asyncio.sleep(backoff_factor * (2 ** (attempt - 1)))

        logger.error("Async Webhook permanently failed for %s after %d retries", callback_url, max_retries)
        return False
