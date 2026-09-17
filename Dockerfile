# ==============================================================================
# SES ANALİZİ PLATFORMU - DOCKERFILE
# ==============================================================================
FROM python:3.11-slim

# Sistem bağımlılıklarının yüklenmesi (FFmpeg, libsndfile, C/C++ derleyiciler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bağımlılık dosyalarının kopyalanması ve yüklenmesi
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Projenin ve bağımlılıkların yüklenmesi
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Tüm uygulama dosyalarının kopyalanması
COPY . .

# Uygulama portunun açılması
EXPOSE 8000

# Varsayılan çalıştırma komutu (FastAPI Web Sunucusu)
CMD ["uvicorn", "audio_analyzer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
