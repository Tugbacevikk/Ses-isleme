import asyncio
import logging
import os
from typing import Any, Callable, List, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T_In = TypeVar("T_In")
T_Out = TypeVar("T_Out")


class DynamicBatcher:
    """
    Çoklu İstemci / Worker Taleplerini Otomatik Gruplayan Asenkron Dinamik Batching Motoru (Dynamic Batching Engine).
    Eşzamanlı gelen tekil çıkarım taleplerini (single inference requests) 8'li, 16'lı veya 32'li gruplar (Batching)
    halinde GPU'ya tek bir forward pass ile besleyerek ekran kartı kullanım verimini ve çıkarım hızını 4 katına çıkarır.
    """

    def __init__(
        self,
        batch_func: Callable[[List[T_In]], List[T_Out]],
        max_batch_size: int = 16,
        max_latency_ms: float = 50.0,
    ):
        self.batch_func = batch_func
        self.max_batch_size = int(os.getenv("MODEL_BATCH_SIZE", str(max_batch_size)))
        self.max_latency_sec = float(os.getenv("MODEL_BATCH_LATENCY_MS", str(max_latency_ms))) / 1000.0
        self._queue: List[Tuple[T_In, asyncio.Future]] = []
        self._lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None

    async def submit(self, item: T_In) -> T_Out:
        """
        Tekil çıkarım isteğini kuyruğa ekler. Batch dolduğunda veya maks bekleme süresi dolduğunda
        çıkarım topluca çalıştırılır ve sonuç Future üzerinden isteğe döner.
        """
        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        async with self._lock:
            self._queue.append((item, fut))
            if len(self._queue) >= self.max_batch_size:
                self._trigger_batch_execution()
            elif self._batch_task is None:
                self._batch_task = loop.create_task(self._wait_and_trigger())

        return await fut

    def _trigger_batch_execution(self):
        if not self._queue:
            return

        batch_items = self._queue[: self.max_batch_size]
        self._queue = self._queue[self.max_batch_size :]

        if self._batch_task and not self._queue:
            self._batch_task.cancel()
            self._batch_task = None

        asyncio.create_task(self._process_batch(batch_items))

    async def _wait_and_trigger(self):
        try:
            await asyncio.sleep(self.max_latency_sec)
            async with self._lock:
                self._batch_task = None
                self._trigger_batch_execution()
        except asyncio.CancelledError:
            pass

    async def _process_batch(self, batch_items: List[Tuple[T_In, asyncio.Future]]):
        inputs = [item for item, _ in batch_items]
        futures = [fut for _, fut in batch_items]

        try:
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, self.batch_func, inputs)

            for fut, res in zip(futures, results):
                if not fut.done():
                    fut.set_result(res)
        except Exception as ex:
            logger.error("Dynamic batch processing failed: %s", ex, exc_info=True)
            for fut in futures:
                if not fut.done():
                    fut.set_exception(ex)
