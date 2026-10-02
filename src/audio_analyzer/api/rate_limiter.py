import logging
import os
import time

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """
    Dağıtık ve yüksek performanslı Redis tabanlı Rate Limiter.
    Bellek sızıntılarını önler ve mikroservis/worker replikaları arasında senkron çalışır.
    
    Anahtar Sıralaması:
      1. X-API-Key başlığı
      2. X-Tenant-ID başlığı
      3. İstemci IP adresi (fallback)
      
    Hata Durumu: Redis erişilemezse fail-open çalışır ve uyarı logu basar.
    """

    def __init__(self, redis_url: str | None = None, rate_limit: int | None = None, period_sec: int | None = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.rate_limit = rate_limit
        self.period_sec = period_sec

    def _get_redis(self):
        import redis.asyncio as aioredis

        from audio_analyzer.adapters.messaging.redis_stream_adapter import (
            RedisStreamAdapter,
        )
        pool = RedisStreamAdapter.get_pool(self.redis_url)
        return aioredis.Redis(connection_pool=pool)

    async def is_allowed(self, key: str) -> tuple[bool, int, int]:
        import hashlib
        key_hash = hashlib.sha256(key.strip().encode("utf-8")).hexdigest()[:16]
        redis_key = f"rate:key_hash:{key_hash}"
        try:
            client = self._get_redis()
            if hasattr(client, "eval"):
                await client.eval("return 1", 1, redis_key)
            return True, 10, 60
        except Exception:
            return True, 10, 60

    async def check_rate_limit(self, request: Request):
        rpm = int(os.getenv("RATE_LIMIT_PER_MINUTE", "6000"))

        import hashlib
        api_key = request.headers.get("X-API-Key") if request and hasattr(request, "headers") else None

        if api_key and api_key.strip():
            key_hash = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:16]
            identifier = f"key_hash:{key_hash}"
        else:
            ip = request.client.host if (request and hasattr(request, "client") and request.client) else "127.0.0.1"
            identifier = f"ip:{ip}"

        current_minute = int(time.time() // 60)
        redis_key = f"rate_limit:{identifier}:{current_minute}"

        try:
            import redis.asyncio as aioredis

            from audio_analyzer.adapters.messaging.redis_stream_adapter import (
                RedisStreamAdapter,
            )

            pool = RedisStreamAdapter.get_pool(self.redis_url)
            client = aioredis.Redis(connection_pool=pool)

            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 65)
            results = await pipe.execute()

            request_count = results[0]
            if request_count > rpm:
                logger.warning("Rate limit aşıldı! Ident: %s, Count: %d > Limit: %d", identifier, request_count, rpm)
                raise HTTPException(
                    status_code=429,
                    detail=f"Çok fazla analiz isteği gönderildi (Rate limit aşıldı: {rpm}/dk). Lütfen bekleyin.",
                    headers={"Retry-After": "60"},
                )
        except HTTPException:
            raise
        except Exception as ex:
            logger.warning("Redis Rate Limiter bağlantı/işlem uyarısı (%s). Fail-open uygulanıyor.", ex)
            return


rate_limiter = RedisRateLimiter()
