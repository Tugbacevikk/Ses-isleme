import asyncio
from unittest.mock import MagicMock

import pytest

from audio_analyzer.services.batch_inference_engine import DynamicBatcher


@pytest.mark.unit
async def test_dynamic_batcher_size_trigger():
    mock_func = MagicMock(side_effect=lambda items: [x * 2 for x in items])
    batcher = DynamicBatcher(batch_func=mock_func, max_batch_size=4, max_latency_ms=1000.0)

    # 4 isteği eşzamanlı fırlat (batch size = 4)
    tasks = [asyncio.create_task(batcher.submit(i)) for i in range(4)]
    results = await asyncio.gather(*tasks)

    assert results == [0, 2, 4, 6]
    # batch_func tam olarak 1 kez 4'lü batch ile çağrılmalı (1 forward pass)
    mock_func.assert_called_once_with([0, 1, 2, 3])


@pytest.mark.unit
async def test_dynamic_batcher_latency_timeout_trigger():
    mock_func = MagicMock(side_effect=lambda items: [f"out_{x}" for x in items])
    # max_batch_size=16 ama 2 eleman ekliyoruz, 50ms sonra zaman aşımı ile çalışmalı
    batcher = DynamicBatcher(batch_func=mock_func, max_batch_size=16, max_latency_ms=50.0)

    task1 = asyncio.create_task(batcher.submit("a"))
    task2 = asyncio.create_task(batcher.submit("b"))

    results = await asyncio.gather(task1, task2)

    assert results == ["out_a", "out_b"]
    mock_func.assert_called_once_with(["a", "b"])


@pytest.mark.unit
async def test_dynamic_batcher_exception_handling():
    def failing_func(items):
        raise RuntimeError("GPU OOM / Compute Error")

    batcher = DynamicBatcher(batch_func=failing_func, max_batch_size=2, max_latency_ms=10.0)

    task1 = asyncio.create_task(batcher.submit(1))
    task2 = asyncio.create_task(batcher.submit(2))

    with pytest.raises(RuntimeError) as exc_info:
        await asyncio.gather(task1, task2)

    assert "GPU OOM" in str(exc_info.value)
