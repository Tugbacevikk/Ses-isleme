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
    """

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or "default_antigravity_secret_key"

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
        Başarısız durumlarda üstel bekleme (backoff) ile max_retries defa yeniden dener.
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

        req = urllib.request.Request(
            callback_url, data=payload_bytes, headers=headers, method="POST"
        )

        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    if 200 <= response.status < 300:
                        logger.info(
                            "Webhook callback successfully delivered to %s (status: %d)",
                            callback_url,
                            response.status,
                        )
                        return True
                    else:
                        logger.warning(
                            "Webhook callback returned non-2xx status (%d) for %s",
                            response.status,
                            callback_url,
                        )
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
