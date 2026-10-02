import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from audio_analyzer.domain.models import AudioRecord, JobStatus
from audio_analyzer.services.retention_service import RetentionService


@pytest.mark.asyncio
async def test_retention_service_uses_get_expired_records_and_batches():
    mock_storage = MagicMock()
    mock_storage.delete.return_value = True

    mock_repo = AsyncMock()

    old_dt = datetime.now(timezone.utc) - timedelta(days=40)
    rec1 = AudioRecord(id=uuid.uuid4(), storage_uri="disk://old1.wav", file_name="old1.wav", status=JobStatus.COMPLETED, created_at=old_dt)
    rec2 = AudioRecord(id=uuid.uuid4(), storage_uri="disk://old2.wav", file_name="old2.wav", status=JobStatus.FAILED, created_at=old_dt)

    # First call returns rec1, rec2; second call returns empty list
    mock_repo.get_expired_records.side_effect = [[rec1, rec2], []]

    svc = RetentionService(storage=mock_storage, repository=mock_repo)

    cleaned = await svc.cleanup_expired_audio_files(retention_hours=24)

    assert cleaned == 2
    assert mock_repo.get_expired_records.called
    assert mock_storage.delete.call_count == 2
