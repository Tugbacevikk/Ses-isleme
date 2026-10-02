from unittest.mock import AsyncMock, patch

import pytest

from audio_analyzer.api.metrics import (
    QUEUE_DEPTH,
    STAGE_DURATION_HISTOGRAM,
    update_dynamic_gauges,
)


@pytest.mark.asyncio
async def test_metrics_queue_depth_xinfo_groups():
    mock_redis = AsyncMock()
    # Mock xinfo_groups returning group data with lag and pending
    mock_redis.xinfo_groups.return_value = [
        {"name": "group1", "lag": 5, "pending": 2},
        {"name": "group2", "lag": 3, "pending": 1},
    ]

    with patch("redis.asyncio.Redis", return_value=mock_redis), patch(
        "audio_analyzer.adapters.messaging.redis_stream_adapter.RedisStreamAdapter.get_pool"
    ), patch("audio_analyzer.api.dependencies.get_uow"):
        await update_dynamic_gauges()

        assert QUEUE_DEPTH._value.get() == 11.0  # (5+2) + (3+1) = 11


def test_stage_duration_histogram_records():
    before_count = STAGE_DURATION_HISTOGRAM.labels(stage="stt")._sum.get()
    STAGE_DURATION_HISTOGRAM.labels(stage="stt").observe(1.25)
    after_count = STAGE_DURATION_HISTOGRAM.labels(stage="stt")._sum.get()
    assert after_count == before_count + 1.25
