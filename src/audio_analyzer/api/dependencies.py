import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.domain.interfaces import ITranscriptRepository

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI Veritabanı Oturumu (Session) Bağımlılığı."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_repository(db: Session = Depends(get_db)) -> ITranscriptRepository:
    """FastAPI Bağımlılık Enjeksiyonu ile ITranscriptRepository örneği sağlar."""
    return PostgresRepository(session=db)


def get_uow() -> SqlAlchemyUnitOfWork:
    """Unit of Work örneği sağlar."""
    return SqlAlchemyUnitOfWork(session_factory=SessionLocal)
