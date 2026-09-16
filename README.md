# Ses Analizi Sistemi (Speech-to-Text & Speaker Diarization)

Yüksek performanslı, modüler, **Clean Architecture / Code-First** prensiplerine uygun olarak tasarlanmış ses analiz sistemi.

## Özellikler
- **Speech-to-Text (STT)**: Faster-Whisper ile zaman damgalı metne dönüştürme.
- **Speaker Diarization**: PyAnnote.audio ile kimin ne zaman konuştuğunu ayrıştırma.
- **Fusion Engine**: IoU ve Midpoint çakışma çözümleme algoritması + 1.5s Sessizlik eşiği.
- **Ayrık Depolama (Separation of Storage)**: MinIO/S3 veya Yerel Disk ses depolama + PostgreSQL meta veri DB.
- **Asenkron Job Queue**: Redis + Celery ile non-blocking HTTP 202 istek işleme.
- **Alembic & Dialect-Agnostic ORM**: SQLite ve PostgreSQL uyumlu SQLAlchemy 2.0 modelleri.
- **Dinamik Donanım (DeviceConfig)**: GPU (CUDA + float16) / CPU (int8 quantization) otomatik tespiti.
- **Pytest Suite**: Unit, Integration ve End-to-End Sistem testleri.

## Kurulum ve Test
```bash
# 1. Sanal ortamı aktifleştirme
.\.venv\Scripts\activate

# 2. Testleri çalıştırma
pytest
```
