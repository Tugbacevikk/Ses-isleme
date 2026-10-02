# ==============================================================================
# SES ANALİZİ PLATFORMU - MULTI-STAGE DOCKERFILE (CPU-ONLY)
# ==============================================================================

# STAGE 1: Builder Stage (Derleme ve Bağımlılık İndirme)
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sanal ortam (venv) oluştur
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 1. CPU-Only PyTorch yükle (pip install -e . öncesinde)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 2. Bağımlılık dosyalarını kopyala ve projeyi yükle
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .


# STAGE 2: Final Runtime Stage (Hafif Üretim İmajı - Derleyiciler İçermez)
FROM python:3.11-slim AS final

# Sadece çalıştırma ortamı bağımlılıkları (FFmpeg ve libsndfile)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Builder aşamasındaki sanal ortamı kopyala
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Uygulama kodunu kopyala
COPY . .

# Güvenlik: Root olmayan yetkisiz kullanıcı (appuser)
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/storage/raw /app/storage/cache && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "audio_analyzer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
