import logging
import os

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
        # PostgreSQL Kurumsal Asenkron Bağlantı Havuzu
        return create_async_engine(
            async_url,
            echo=False,
            pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_pre_ping=True,
            pool_recycle=3600,
        )


def init_engine():
    db_url = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
    try:
        eng = create_async_db_engine(db_url)
        if not db_url.startswith("sqlite"):
            import asyncio
            from sqlalchemy import text

            async def test_connection():
                async with eng.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(lambda: asyncio.run(test_connection())).result()
            else:
                asyncio.run(test_connection())

        return eng
    except Exception as e:
        allow_fallback = os.getenv("ALLOW_SQLITE_FALLBACK", "false").lower() == "true"
        if allow_fallback and "sqlite" not in db_url:
            fallback_url = "sqlite:///storage/dev_database.db"
            logger.warning(
                "PostgreSQL bağlantı hatası (%s). ALLOW_SQLITE_FALLBACK=true olduğu için yerel SQLite (%s) tamponuna geçiliyor.",
                e,
                fallback_url,
            )
            return create_async_db_engine(fallback_url)
        else:
            logger.error(
                "Veritabanı bağlantı hatası (%s). ALLOW_SQLITE_FALLBACK=false olduğu için uygulama durduruluyor (Loud Fail / Anti-Split-Brain).",
                e,
            )
            raise e


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

