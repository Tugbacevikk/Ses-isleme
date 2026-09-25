import logging
import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.domain.interfaces import ITranscriptRepository

logger = logging.getLogger(__name__)


def get_async_db_url(url: str) -> str:
    """
    DB URL'sini async dialect sürücüsüne dönüştürür.
    postgresql:// -> postgresql+asyncpg://
    sqlite:/// -> sqlite+aiosqlite:///
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def create_async_db_engine(db_url: str):
    """
    PostgreSQL (asyncpg) / SQLite (aiosqlite) asenkron veritabanı motoru oluşturan fabrika fonksiyonu.
    PostgreSQL için havuzlama (pool_size, max_overflow, pool_pre_ping) parametrelerini aktif eder.
    """
    async_url = get_async_db_url(db_url)
    if "sqlite" in async_url:
        eng = create_async_engine(async_url, echo=False)

        @event.listens_for(eng.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return eng
    else:
        import sys
        from sqlalchemy.pool import NullPool

        is_testing = os.getenv("TESTING", "false").lower() == "true" or "pytest" in sys.modules
        if is_testing:
            return create_async_engine(async_url, echo=False, poolclass=NullPool)

        # PostgreSQL Kurumsal Asenkron Bağlantı Havuzu
        return create_async_engine(
            async_url,
            echo=False,
            pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_recycle=3600,
        )



def init_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
    allow_fallback = os.getenv("ALLOW_SQLITE_FALLBACK", "false").lower() == "true"

    if allow_fallback and not db_url.startswith("sqlite"):
        fallback_url = "sqlite:///storage/dev_database.db"
        logger.warning(
            "ALLOW_SQLITE_FALLBACK=true olduğu için yerel SQLite (%s) tamponuna geçiliyor.",
            fallback_url,
        )
        return create_async_db_engine(fallback_url)

    logger.info("Veritabanı motoru başlatılıyor: %s", get_async_db_url(db_url))
    return create_async_db_engine(db_url)




engine = init_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession
)
SessionLocal = AsyncSessionLocal


async def get_db():
    """FastAPI Asenkron Veritabanı Oturumu (AsyncSession) Bağımlılığı."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_repository(db: AsyncSession = Depends(get_db)) -> ITranscriptRepository:
    """FastAPI Bağımlılık Enjeksiyonu ile ITranscriptRepository örneği sağlar."""
    return PostgresRepository(session=db)


def get_uow() -> SqlAlchemyUnitOfWork:
    """Unit of Work örneği sağlar."""
    return SqlAlchemyUnitOfWork(session_factory=AsyncSessionLocal)

