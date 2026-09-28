import asyncio
import logging
import os
import signal
import uuid
from typing import Optional

from audio_analyzer.adapters.messaging.redis_stream_adapter import RedisStreamAdapter
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.adapters.storage.storage_factory import get_storage_adapter
from audio_analyzer.api.dependencies import AsyncSessionLocal
from audio_analyzer.services.job_service import JobService

logger = logging.getLogger(__name__)


import contextlib
import time


class RedisStreamWorker:
    """
    Redis Streams Tüketici Grubu (Consumer Group) Worker Hizmeti.
    100+ sunucuda eşzamanlı olarak çalışarak Redis Stream üzerinden gelen işleri
    sıfır kilitlenme (key contention) ve tam paralellikle tüketir.
    """

    def __init__(
        self,
        consumer_name: Optional[str] = None,
        adapter: Optional[RedisStreamAdapter] = None,
    ):
        self.consumer_name = consumer_name or f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self.adapter = adapter or RedisStreamAdapter()
        self.running = False

    async def _heartbeat_loop(self, msg_id: str, interval_sec: float = 15.0):
        try:
            while self.running:
                await asyncio.sleep(interval_sec)
                await self.adapter.claim_message_heartbeat(self.consumer_name, msg_id)
        except asyncio.CancelledError:
            pass

    async def process_single_message(self, msg_id: str, fields: dict) -> bool:
        """Tek bir Redis Stream mesajını çözer, JobService ile yürütür ve karara göre ACK / RETRY / DLQ yönetir."""
        job_id_str = fields.get("job_id")
        if not job_id_str:
            logger.warning("Eksik job_id içeren mesaj es geçiliyor: %s", msg_id)
            await self.adapter.ack_message(msg_id)
            return False

        hb_task = asyncio.create_task(self._heartbeat_loop(msg_id))
        try:
            record_id = uuid.UUID(job_id_str)
            uow = SqlAlchemyUnitOfWork(session_factory=AsyncSessionLocal)
            storage = get_storage_adapter()

            async with uow:
                from audio_analyzer.services.pipeline_factory import get_shared_pipeline

                pipeline = get_shared_pipeline()
                job_service = JobService(storage=storage, repository=uow.repository, pipeline=pipeline)
                res_status, attempts, err_msg = await job_service.execute_job_detailed(record_id)

            if res_status in ("COMPLETED", "SKIPPED"):
                await self.adapter.ack_message(msg_id)
                logger.info(
                    "Worker %s job_id=%s mesajını başardı (%s) ve XACK onayladı.",
                    self.consumer_name,
                    job_id_str,
                    res_status,
                )
                return True
            elif res_status == "FAILED":
                # Kalıcı hata veya Maksimum deneme aşıldı -> Dead-Letter Stream'e aktar ve XACK et
                await self.adapter.publish_to_dlq(
                    job_id=job_id_str,
                    error_message=err_msg or "Unkown Failure",
                    attempts=attempts,
                )
                await self.adapter.ack_message(msg_id)
                logger.warning(
                    "Worker %s job_id=%s (attempts=%d) FAILED durumunda DLQ'ya atıldı ve XACK onaylandı.",
                    self.consumer_name,
                    job_id_str,
                    attempts,
                )
                return False
            elif res_status == "RETRY":
                # Geçici hata -> Üstel backoff sonrası yeniden akışa yayınla ve eski mesajı XACK et
                backoff_sec = min(30.0, float(2 ** max(0, attempts - 1)))
                logger.info(
                    "Worker %s job_id=%s (attempts=%d) geçici hata aldı. %.1f sn backoff sonrası yeniden akışa yayınlanıyor.",
                    self.consumer_name,
                    job_id_str,
                    attempts,
                    backoff_sec,
                )
                await asyncio.sleep(backoff_sec)
                await self.adapter.publish_job(
                    job_id=job_id_str,
                    file_name=fields.get("file_name", ""),
                    callback_url=fields.get("callback_url", None),
                )
                await self.adapter.ack_message(msg_id)
                return False
            else:
                await self.adapter.ack_message(msg_id)
                return False

        except Exception as ex:
            logger.error(
                "Worker %s msg_id=%s beklenmeyen hata aldı: %s",
                self.consumer_name,
                msg_id,
                ex,
                exc_info=True,
            )
            return False
        finally:
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task

    async def run(self):
        """Worker döngüsünü başlatır (XREADGROUP + XAUTOCLAIM)."""
        self.running = True
        prefetch_count = int(os.getenv("WORKER_PREFETCH", "1"))
        min_idle_ms = int(os.getenv("STREAM_CLAIM_IDLE_MS", "900000"))
        claim_interval_sec = float(os.getenv("STREAM_CLAIM_INTERVAL_SEC", "60"))

        logger.info(
            "Redis Stream Worker başlatılıyor: consumer_name=%s, prefetch=%d, claim_idle_ms=%d",
            self.consumer_name,
            prefetch_count,
            min_idle_ms,
        )

        await self.adapter.create_consumer_group()
        last_claim_time = time.monotonic()

        while self.running:
            try:
                # 1. Okunmamış mesajları XREADGROUP ile çek (WORKER_PREFETCH)
                messages = await self.adapter.consume_messages(
                    consumer_name=self.consumer_name,
                    count=prefetch_count,
                    block_ms=1000,
                )

                for msg_id, fields in messages:
                    if not self.running:
                        break
                    await self.process_single_message(msg_id, fields)

                # 2. Periyodik olarak (zamana bağlı STREAM_CLAIM_INTERVAL_SEC) yetim mesajları XAUTOCLAIM ile devral
                now = time.monotonic()
                if now - last_claim_time >= claim_interval_sec:
                    last_claim_time = now
                    claimed = await self.adapter.claim_pending_messages(
                        consumer_name=self.consumer_name,
                        min_idle_time_ms=min_idle_ms,
                        count=prefetch_count,
                    )
                    for msg_id, fields in claimed:
                        logger.info(
                            "Worker %s sahipsiz kalan %s mesajını XAUTOCLAIM ile devraldı.",
                            self.consumer_name,
                            msg_id,
                        )
                        await self.process_single_message(msg_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error("Worker döngü hatası: %s", err, exc_info=True)
                await asyncio.sleep(1.0)

        logger.info("Redis Stream Worker durduruldu: consumer_name=%s", self.consumer_name)

    def stop(self):
        self.running = False


async def start_worker_main():
    os.environ.setdefault("USE_REDIS_STREAM", "true")
    from audio_analyzer.utils.cpu_budget import setup_cpu_thread_budget
    from audio_analyzer.adapters.storage.storage_factory import assert_storage_shared_across_processes

    setup_cpu_thread_budget()
    assert_storage_shared_across_processes()

    worker = RedisStreamWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            pass  # Windows signals

    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_worker_main())
