import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.domain.models import AudioRecord, JobStatus


@pytest.fixture
def in_memory_uow():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return SqlAlchemyUnitOfWork(session_factory)


def test_unit_of_work_commit_and_rollback(in_memory_uow):
    record_id = uuid.uuid4()
    record = AudioRecord(
        id=record_id,
        storage_uri="file:///tmp/uow_test.wav",
        file_name="uow_test.wav",
        status=JobStatus.PENDING,
    )

    # 1. Commit Flow via UoW Context Manager
    with in_memory_uow as uow:
        uow.repository.save_record(record)
        uow.commit()

    # Verify saved
    with in_memory_uow as uow:
        retrieved = uow.repository.get_record_by_id(record_id)
        assert retrieved is not None
        assert retrieved.file_name == "uow_test.wav"

    # 2. Rollback Flow on Exception
    failed_id = uuid.uuid4()
    failed_record = AudioRecord(
        id=failed_id,
        storage_uri="file:///tmp/fail.wav",
        file_name="fail.wav",
        status=JobStatus.PENDING,
    )

    try:
        with in_memory_uow as uow:
            uow.repository.save_record(failed_record)
            raise RuntimeError("Simulated transaction error")
    except RuntimeError:
        pass

    # Verify rolled back
    with in_memory_uow as uow:
        retrieved_failed = uow.repository.get_record_by_id(failed_id)
        assert retrieved_failed is None
