# Ses Analizi Sistemi (STT & Speaker Diarization)
## Mühendislik Tasarım Dokümanı ve Yol Haritası (Blueprint)

Bu doküman; **Speech-to-Text (Metne Dönüştürme)**, **Speaker Diarization (Konuşmacı Ayrıştırma)**, **Dinamik Donanım Yönetimi (Device Management - GPU/CPU/Quantization)**, **Fusion Engine Zaman Eşleme & Çakışma Çözümleme Algoritması**, **Ayrık Depolama Mimarisi (Separation of Storage)**, **Asenkron Görev Kuyruğu (Task Queue - Celery/Redis)**, **Kapsamlı Sistem & E2E Test Stratejisi (Test Pyramid)**, **Veritabanından Bağımsız (Dialect-Agnostic) SQLAlchemy 2.0 ORM** ve **Alembic Veritabanı Migrasyon Yapısını** içeren, modüler, ölçeklenebilir ve üretim seviyesi (Production-Ready) **Clean Architecture / Code-First** yazılım projesi mimarisini tanımlar.

---

## 1. Mimari Tasarım ve Prensipler

### 1.1 Clean / Hexagonal Architecture
Proje 3 temel katmandan oluşur:
- **Domain Katmanı (Core)**: İş kuralları, Pydantic veri modelleri, `DeviceConfig` donanım yapılandırması ve abstract arayüzler (`IAudioStorage`, `ITranscriptRepository`, `ISTTEngine`, `IDiarizer`). Dış kütüphanelerden tamamen bağımsızdır.
- **Service / Pipeline Katmanı**: İş akışlarının orkestrasyonu (Ses Alımı -> VAD -> STT -> Diarization -> **FusionEngine** -> Persistence).
- **Adapters & Worker Katmanı**: GPU/CPU donanım adaptörleri, Celery / Redis Task Queue worker'ları, SQLAlchemy ORM modelleri veya Rust modülleri.

### 1.2 Kapsamlı Sistem ve E2E Test Stratejisi (Test Pyramid)
Yazılımın güvenilirliğini, geriye dönük uyumluluğunu (Regression) ve doğruluğunu sağlamak için 4 seviyeli test piramidi:
1. **Birim Testleri (`tests/unit/`)**:
   - `sqlite:///:memory:` üzerinde milisaniyeler içinde çalışan mock testler.
   - `FusionEngine` IoU çakışma ve sessizlik eşiği algoritma doğrulamaları.
   - `DeviceConfig` donanım seçici testleri.
2. **Entegrasyon Testleri (`tests/integration/`)**:
   - `LocalStorageAdapter` ses yazma/okuma testleri.
   - `PostgresRepository` CRUD işlemleri ve veritabanı ilişkileri testleri.
3. **End-to-End (E2E) Sistem Testleri (`tests/system/`)**:
   - Örnek sentetik 2-3 saniyelik test ses dosyası (`fixture.wav`) ile uçtan uca test:
   - Ses Yükleme -> Görev Oluşturma (`PENDING`) -> Worker Çalıştırma -> DB Kaydı (`COMPLETED`) -> Metin/Konuşmacı Çıktısı Doğrulama (`language`, `speaker_id`, `timestamps`).
4. **Performans ve Benchmark Testleri (`tests/benchmark/`)**:
   - Real-Time Factor (RTF) ölçümü (İşleme Süresi / Ses Süresi).
   - Python ve Rust DSP modülleri hız karşılaştırma testleri.

---

## 2. Code-First Dialect-Agnostic SQLAlchemy 2.0 ORM Modelleri

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class AudioRecordModel(Base):
    __tablename__ = "audio_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int] = mapped_column(Integer, default=16000)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True) # Whisper'ın tespit ettiği dil (tr, en vb.)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")     # PENDING, PROCESSING, COMPLETED, FAILED
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True) # Hata detay açıklaması
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    utterances: Mapped[list["TranscriptUtteranceModel"]] = relationship(
        back_populates="audio_record", cascade="all, delete-orphan"
    )

class TranscriptUtteranceModel(Base):
    __tablename__ = "transcript_utterances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audio_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audio_records.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    audio_record: Mapped["AudioRecordModel"] = relationship(back_populates="utterances")

    __table_args__ = (
        Index("idx_utterances_audio_id", "audio_record_id"),
        Index("idx_utterances_speaker", "speaker_id"),
    )
```

---

## 3. Proje Dizin Yapısı (Test Mimarisi Dahil)

```
sesAnalizi/
├── Sistem_Mimarisi_ve_Yol_Haritasi.md   # Bu Blueprint Dokümanı
├── pyproject.toml                        # uv / poetry / pytest bağımlılıkları
├── alembic.ini                           # Alembic Yapılandırma Dosyası
├── alembic/                              # DB Migrasyon Yönetimi
│   ├── env.py
│   └── versions/
├── storage/                              # Yerel geliştirme depolama alanı (.gitignore)
│   ├── raw/
│   └── processed/
├── src/
│   └── audio_analyzer/
│       ├── __init__.py
│       ├── domain/                       # Pure Python Domain & Pydantic Schemas
│       │   ├── models.py                 # Pydantic Schemas (DeviceConfig, Utterance, WordSegment)
│       │   └── interfaces.py             # Interfaces (IAudioStorage, ITranscriptRepository, STT, Diarizer)
│       ├── services/                     # Pipeline & Algoritma Katmanı
│       │   ├── pipeline.py               # Main Analysis Pipeline
│       │   ├── fusion_engine.py          # Midpoint + IoU + Silence Alignment Algoritması
│       │   └── job_service.py            # Job Creation & Status Management
│       ├── workers/                      # Asenkron Worker Katmanı (Celery / ARQ)
│       │   ├── celery_app.py
│       │   └── tasks.py
│       ├── adapters/                     # Entegrasyonlar (Device-Aware Adapters)
│       │   ├── stt/
│       │   │   └── faster_whisper_adapter.py
│       │   ├── diarization/
│       │   │   └── pyannote_adapter.py
│       │   ├── storage/
│       │   │   ├── local_storage_adapter.py
│       │   │   └── s3_storage_adapter.py
│       │   ├── repository/
│       │   │   ├── models.py
│       │   │   └── postgres_repository.py
│       │   └── audio/
│       │       └── numpy_processor.py
│       └── utils/
│           └── audio_io.py
├── native/                               # Rust Crate (PyO3)
│   ├── Cargo.toml
│   └── src/
│       └── lib.rs
└── tests/                                # Test Mimarisi (Pytest)
    ├── fixtures/                         # Test verileri ve sentetik ses dosyaları (.wav)
    │   └── sample_2sec.wav
    ├── conftest.py                       # Global Pytest Fixtures (in-memory db, mock adapters)
    ├── unit/                             # Birim testler (FusionEngine IoU, DeviceConfig)
    │   ├── test_fusion_engine.py
    │   └── test_device_config.py
    ├── integration/                      # Entegrasyon testleri (Storage & Repository)
    │   ├── test_storage_adapter.py
    │   └── test_repository.py
    └── system/                           # End-to-End Sistem testleri (E2E Pipeline)
        └── test_full_pipeline.py
```

---

## 4. Sistem Testi Örnek Senaryosu (`tests/system/test_full_pipeline.py`)

```python
import pytest
from audio_analyzer.services.job_service import JobService
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.domain.models import DeviceConfig

@pytest.mark.system
def test_full_audio_analysis_pipeline_e2e(mock_storage, in_memory_repository, mock_stt, mock_diarizer):
    """
    Tüm sistemin uçtan uca (E2E) entegre çalışmasını ve veri tutarlılığını test eder.
    """
    pipeline = AudioAnalysisPipeline(
        stt_engine=mock_stt,
        diarizer=mock_diarizer,
        device_config=DeviceConfig(device="cpu", compute_type="int8")
    )
    job_service = JobService(storage=mock_storage, repo=in_memory_repository, pipeline=pipeline)

    # 1. Ses dosyası yükleme ve iş oluşturma
    job_id = job_service.create_job(file_name="sample.wav", file_bytes=b"RIFF_MOCK_WAV_HEADER...")
    record_initial = in_memory_repository.get_by_id(job_id)
    assert record_initial.status == "PENDING"

    # 2. Worker çalıştırma (Synchronous test execution)
    job_service.execute_job(job_id)

    # 3. Sonuçların veritabanından doğrulanması
    record_final = in_memory_repository.get_by_id(job_id)
    assert record_final.status == "COMPLETED"
    assert record_final.language is not None
    assert len(record_final.utterances) > 0
    assert record_final.utterances[0].speaker_id.startswith("SPEAKER_")
```

---

## 5. Uygulama Adımları (Roadmap)

### Adım 1: Temel Bağımlılıklar, ORM, DeviceConfig & Domain Katmanı
- Bağımlılıkların kurulması (`torch`, `sqlalchemy`, `alembic`, `celery`, `redis`, `pydantic`, `pytest`, `faster-whisper`, `pyannote.audio`).
- `DeviceConfig` ve ORM modellerinin yazılması, Alembic migrasyonunun ilk versiyonu.

### Adım 2: Test Mimarisi ve Unit Testlerin Yazılması
- `tests/conftest.py` içinde `in_memory_db` ve sentetik test ses dosyasının (`fixtures/sample_2sec.wav`) hazırlanması.
- `FusionEngine` IoU çakışma algoritması unit testlerinin yazılması (`test_fusion_engine.py`).

### Adım 3: Device-Aware STT & Diarization Adaptörleri
- `FasterWhisperAdapter` ve `PyAnnoteAdapter` geliştirmesi.

### Adım 4: Storage & Repository Adaptörleri (Entegrasyon Testleri)
- `LocalStorageAdapter` ve `PostgresRepository` entegrasyon testlerinin yazılması (`test_repository.py`).

### Adım 5: Asenkron Worker & End-to-End Sistem Testi
- Celery worker görevlerinin entegre edilmesi ve `tests/system/test_full_pipeline.py` E2E sistem testinin çalıştırılması.

### Adım 6: Rust Performans Katmanı
- Ses ön işleme adımlarının Rust (`PyO3`) ile hızlandırılması.m
