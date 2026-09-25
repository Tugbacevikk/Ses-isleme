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

    async def process_single_message(self, msg_id: str, fields: dict) -> bool:
        """Tek bir Redis Stream mesajını çözer, JobService ile yürütür ve XACK onaylar."""
        job_id_str = fields.get("job_id")
        if not job_id_str:
            logger.warning("Eksik job_id içeren mesaj es geçiliyor: %s", msg_id)
            await self.adapter.ack_message(msg_id)
            return False

        try:
            record_id = uuid.UUID(job_id_str)
            uow = SqlAlchemyUnitOfWork(session_factory=AsyncSessionLocal)
            storage = get_storage_adapter()

            async with uow:
                from audio_analyzer.services.pipeline_factory import get_shared_pipeline

                pipeline = get_shared_pipeline()
                job_service = JobService(storage=storage, repository=uow.repository, pipeline=pipeline)
                success = await job_service.execute_job(record_id)

            await self.adapter.ack_message(msg_id)
            logger.info(
                "Worker %s job_id=%s mesajını başardı ve XACK onayladı (msg_id=%s).",
                self.consumer_name,
                job_id_str,
                msg_id,
            )
            return success
        except Exception as ex:
            logger.error(
                "Worker %s msg_id=%s işlerken hata aldı: %s",
                self.consumer_name,
                msg_id,
                ex,
                exc_info=True,
            )
            return False

    async def run(self):
        """Worker döngüsünü başlatır (XREADGROUP + XAUTOCLAIM)."""
        self.running = True
        logger.info("Redis Stream Worker başlatılıyor: consumer_name=%s", self.consumer_name)

        await self.adapter.create_consumer_group()

        claim_counter = 0

        while self.running:
            try:
                # 1. Okunmamış mesajları XREADGROUP ile çek
                messages = await self.adapter.consume_messages(
                    consumer_name=self.consumer_name,
                    count=10,
                    block_ms=1000,
                )

                for msg_id, fields in messages:
                    if not self.running:
                        break
                    await self.process_single_message(msg_id, fields)

                # 2. Periyodik olarak (her 10 döngüde bir) yarım kalan yetim mesajları XAUTOCLAIM ile devral
                claim_counter += 1
                if claim_counter >= 10:
                    claim_counter = 0
                    claimed = await self.adapter.claim_pending_messages(
                        consumer_name=self.consumer_name,
                        min_idle_time_ms=60000,
                        count=5,
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
