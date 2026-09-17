from sqlalchemy.orm import Session, sessionmaker
from audio_analyzer.domain.interfaces import IUnitOfWork
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository


class SqlAlchemyUnitOfWork(IUnitOfWork):
    """
    SQLAlchemy için Unit-of-Work (UoW) Desen Adaptörü.
    Transaction sınırlarını (commit, rollback, session kapama) tek bir noktada toplar
    ve veritabanı işlemlerinin atomik olmasını garanti eder.
    """

    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory
        self.session: Session = None
        self.repository: PostgresRepository = None

    def __enter__(self):
        self.session = self.session_factory()
        self.repository = PostgresRepository(self.session, autocommit=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        if self.session:
            self.session.close()

    def commit(self):
        if self.session:
            self.session.commit()

    def rollback(self):
        if self.session:
            self.session.rollback()
