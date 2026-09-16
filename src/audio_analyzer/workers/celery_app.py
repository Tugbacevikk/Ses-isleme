import os
from celery import Celery

# Redis Broker ve Result Backend bağlantı URL'si (Ortam değişkeninden veya varsayılan yerel adresten alır)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Celery Uygulaması Yapılandırması
celery_app = Celery(
    "audio_analyzer_workers",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["audio_analyzer.workers.tasks"],
)

# Celery İnce Ayarları (Task Serialization, Concurrency, Timeouts)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Ağır yapay zeka modelleri (Whisper/PyAnnote) çalışırken worker'ın kilitlenmemesi için prefetc_multiplier = 1
    worker_prefetch_multiplier=1,
)
