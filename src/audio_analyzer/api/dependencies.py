import logging
import os

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.domain.interfaces import ITranscriptRepository

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")


def create_db_engine(db_url: str):
    """
    PostgreSQL / SQLite veritabanı motoru oluşturan fabrika fonksiyonu.
    PostgreSQL için havuzlama (pool_size, max_overflow, pool_pre_ping) parametrelerini aktif eder.
    """
    if db_url.startswith("sqlite"):
        engine = create_engine(
            db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
        )
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    else:
        # PostgreSQL Kurumsal Bağlantı Havuzu
        return create_engine(
            db_url,
            echo=False,
            pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_pre_ping=True,
            pool_recycle=3600,
        )


try:
    engine = create_db_engine(DATABASE_URL)
    # Tabloları otomatik kontrol et/oluştur
    from audio_analyzer.adapters.repository.models import Base

    Base.metadata.create_all(engine)
except Exception as e:
    fallback_url = "sqlite:///storage/dev_database.db"
    logger.warning(
        "PostgreSQL bağlantı hatası (%s). Yerel SQLite (%s) tamponuna geçiliyor.", e, fallback_url
    )
    engine = create_db_engine(fallback_url)
    from audio_analyzer.adapters.repository.models import Base

    Base.metadata.create_all(engine)

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
