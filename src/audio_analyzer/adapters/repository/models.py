import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Python 3.12+ uyumlu timezone-aware UTC datetime üreticisi."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """SQLAlchemy ORM modelleri için temel sınıf."""

    pass


class AudioRecordModel(Base):
    """
    Ses Kaydı Veritabanı Tablosu.
    PostgreSQL'de native UUID, SQLite'ta CHAR(32) olarak derlenir (Dialect-Agnostic).
    """

    __tablename__ = "audio_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int] = mapped_column(Integer, default=16000)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, server_default=func.now()
    )

    # 1-to-N ilişki: Bir ses kaydının birden fazla konuşmacı cümlesi olur.
    utterances: Mapped[list["TranscriptUtteranceModel"]] = relationship(
        back_populates="audio_record", cascade="all, delete-orphan"
    )


class TranscriptUtteranceModel(Base):
    """
    Zaman Damgalı Konuşmacı Cümleleri Veritabanı Tablosu.
    """

    __tablename__ = "transcript_utterances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audio_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audio_records.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    audio_record: Mapped["AudioRecordModel"] = relationship(back_populates="utterances")

    __table_args__ = (
        Index("idx_utterances_audio_id", "audio_record_id"),
        Index("idx_utterances_speaker", "speaker_id"),
    )
