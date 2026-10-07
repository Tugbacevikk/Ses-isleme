import concurrent.futures
import time
from unittest.mock import MagicMock, patch
import pytest

from audio_analyzer.services.pipeline_factory import (
    get_shared_pipeline,
    reset_pipeline_cache,
)


@pytest.mark.unit
def test_get_shared_pipeline_concurrency():
    reset_pipeline_cache()

    call_count = 0
    mock_pipeline_inst = MagicMock()

    def slow_build_pipeline():
        nonlocal call_count
        call_count += 1
        time.sleep(0.1)
        return mock_pipeline_inst

    with patch("audio_analyzer.services.pipeline_factory._build_pipeline", side_effect=slow_build_pipeline) as mock_build:
        def worker_task():
            return get_shared_pipeline()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task) for _ in range(8)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert call_count == 1
        mock_build.assert_called_once()
        for res in results:
            assert res is mock_pipeline_inst

    reset_pipeline_cache()
