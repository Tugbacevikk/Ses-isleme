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
        import os

        self.secret_key = secret_key or os.getenv(
            "WEBHOOK_SECRET", "default_antigravity_secret_key"
        )

    @classmethod
    def get_sync_client(cls):
        """High-throughput sync connection pooling için paylaşımlı httpx.Client."""
        if cls._sync_client is None:
            try:
                import httpx

                limits = httpx.Limits(max_keepalive_connections=200, max_connections=1000)
                cls._sync_client = httpx.Client(timeout=10.0, limits=limits)
            except Exception as e:
                logger.warning("httpx.Client initialize warning (%s), falling back to urllib", e)
                return None
        return cls._sync_client

    @classmethod
    def get_async_client(cls):
        """High-throughput async connection pooling için paylaşımlı httpx.AsyncClient."""
        if cls._async_client is None:
            try:
                import httpx

                limits = httpx.Limits(max_keepalive_connections=200, max_connections=1000)
                cls._async_client = httpx.AsyncClient(timeout=10.0, limits=limits)
            except Exception as e:
                logger.warning("httpx.AsyncClient initialize warning (%s)", e)
                return None
        return cls._async_client

    def generate_signature(self, payload_bytes: bytes) -> str:
        """Payload veri bütünlüğünü garanti etmek için HMAC-SHA256 imzası üretir."""
        return hmac.new(
            self.secret_key.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()

    def send_callback(
        self,
        callback_url: str,
        payload: Dict[str, Any],
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> bool:
        """
        Hedef callback_url adresine JSON formatında HTTP POST isteği atar.
        httpx TCP keep-alive bağlantı havuzu (connection pool) kullanır.
        """
        if not callback_url:
            return False

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        signature = self.generate_signature(payload_bytes)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Antigravity-Audio-Analyzer-Webhook/1.0",
            "X-Signature": signature,
        }

        client = self.get_sync_client()

        for attempt in range(1, max_retries + 1):
            try:
                if client is not None:
                    resp = client.post(callback_url, content=payload_bytes, headers=headers)
                    if 200 <= resp.status_code < 300:
                        logger.info(
                            "Webhook callback successfully delivered to %s (status: %d)",
                            callback_url,
                            resp.status_code,
                        )
                        return True
                    else:
                        logger.warning(
                            "Webhook callback returned non-2xx status (%d) for %s",
                            resp.status_code,
                            callback_url,
                        )
                else:
                    # Fallback to urllib
                    req = urllib.request.Request(
                        callback_url, data=payload_bytes, headers=headers, method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=10) as response:
                        if 200 <= response.status < 300:
                            logger.info(
                                "Webhook callback successfully delivered via urllib to %s (%d)",
                                callback_url,
                                response.status,
                            )
                            return True
            except Exception as ex:
                logger.warning(
                    "Webhook callback attempt %d/%d failed for %s: %s",
                    attempt,
                    max_retries,
                    callback_url,
                    ex,
                )

            if attempt < max_retries:
                sleep_time = backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_time)

        logger.error(
            "Webhook callback permanently failed for %s after %d retries.",
            callback_url,
            max_retries,
        )
        return False

    async def send_callback_async(
        self,
        callback_url: str,
        payload: Dict[str, Any],
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> bool:
        """
        Yüksek eşzamanlılık (4k-5k req/sec) için asenkron non-blocking HTTP POST webhook callback gönderici.
        """
        if not callback_url:
            return False

        import asyncio
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        signature = self.generate_signature(payload_bytes)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Antigravity-Audio-Analyzer-Webhook/1.0",
            "X-Signature": signature,
        }

        client = self.get_async_client()
        if client is None:
            return self.send_callback(callback_url, payload, max_retries, backoff_factor)

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
