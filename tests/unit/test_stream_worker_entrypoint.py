import pytest
from unittest.mock import AsyncMock, patch
from audio_analyzer.workers.stream_worker import start_worker_main


@pytest.mark.asyncio
async def test_start_worker_main_runs_worker():
    with patch("audio_analyzer.workers.stream_worker.RedisStreamWorker") as mock_worker_cls, \
         patch("audio_analyzer.adapters.storage.storage_factory.assert_storage_shared_across_processes"):
        mock_worker_inst = mock_worker_cls.return_value
        mock_worker_inst.run = AsyncMock()

        await start_worker_main()

        mock_worker_inst.run.assert_awaited_once()
