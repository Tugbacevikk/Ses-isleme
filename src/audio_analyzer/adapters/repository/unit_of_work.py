from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.domain.interfaces import IUnitOfWork


class SqlAlchemyUnitOfWork(IUnitOfWork):
    """
    SQLAlchemy için Async Unit-of-Work (UoW) Desen Adaptörü.
    Transaction sınırlarını (commit, rollback, session kapama) tek bir noktada toplar
    ve veritabanı işlemlerinin atomik olmasını garanti eder.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.session: AsyncSession | None = None
        self.repository: PostgresRepository | None = None

    async def __aenter__(self):
        self.session = self.session_factory()
        self.repository = PostgresRepository(self.session, autocommit=False)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
        if self.session:
            await self.session.close()

    async def commit(self):
        if self.session:
            await self.session.commit()

    async def rollback(self):
        if self.session:
            await self.session.rollback()

