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


def init_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
    try:
        eng = create_db_engine(db_url)
        # PostgreSQL için bağlantıyı hemen test et
        if not db_url.startswith("sqlite"):
            from sqlalchemy import text
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        return eng
    except Exception as e:
        allow_fallback = os.getenv("ALLOW_SQLITE_FALLBACK", "false").lower() == "true"
        if allow_fallback and not db_url.startswith("sqlite"):
            fallback_url = "sqlite:///storage/dev_database.db"
            logger.warning(
                "PostgreSQL bağlantı hatası (%s). ALLOW_SQLITE_FALLBACK=true olduğu için yerel SQLite (%s) tamponuna geçiliyor.",
                e,
                fallback_url,
            )
            return create_db_engine(fallback_url)
        else:
            logger.error(
                "Veritabanı bağlantı hatası (%s). ALLOW_SQLITE_FALLBACK=false olduğu için uygulama durduruluyor (Loud Fail / Anti-Split-Brain).",
                e,
            )
            raise e


engine = init_engine()
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
