# Ses Analizi Sistemi (Speech-to-Text & Speaker Diarization)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

Yüksek performanslı, modüler, **Clean Architecture / Code-First** prensiplerine uygun olarak tasarlanmış ses analiz sistemi.

## Özellikler
- **Speech-to-Text (STT)**: Faster-Whisper ile zaman damgalı metne dönüştürme (`tiny`, `small`, `medium` model desteği).
- **Çok Kademeli Speaker Diarization (Fallback Chain)**:
  - **1. Kademe**: SOTA PyAnnote 3.1 (HuggingFace Gated Model).
  - **2. Kademe**: SpeechBrain ECAPA-TDNN (%100 Çevrimdışı & Token-Free).
  - **3. Kademe**: Local Spectral Clustering (Tamamen yerel akustik kümeleme).
- **SemanticRefiner & Yerel LLM Entegrasyonu**:
  - Alan Odaklı Kurallar (`domain_mode="call_center"` ile müşteri/temsilci geçiş tespiti).
  - Opsiyonel yerel Ollama LLM (`llama3.2` / `qwen2.5`) entegrasyonu ile konuşmacı metinlerinin anlamsal iyileştirilmesi.
- **Fusion Engine**: IoU ve Midpoint çakışma çözümleme algoritması + 1.5s sessizlik eşiği.
- **Voice Activity Detection (VAD)**: Silero VAD ile gürültü ve sessizlik halüsinasyon filtrelemesi.
- **Rust PyO3 Native DSP Accelerator**: Rust ile yazılmış C-hızında sıfır gecikmeli resample, VAD ve kosinüs benzerliği modülü.
- **Asenkron Job Queue**: Redis + Celery ve FastAPI BackgroundTasks ile non-blocking HTTP 202 istek işleme.
- **Sıcak Yükleme (Warm-Loading)**: Singleton AI Pipeline ile hızlı ve düşük gecikmeli analiz.

## HuggingFace & Diarization Yapılandırması

PyAnnote 3.1 (1. Kademe) kullanmak için:
1. [HuggingFace Tokens](https://huggingface.co/settings/tokens) adresinden `Read` izinli bir erişim anahtarı oluşturun.
2. `.env` dosyanıza `HF_TOKEN=hf_...` olarak ekleyin.
3. Aşağıdaki 3 model sayfasındaki kullanım şartlarını onaylayın:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

> ℹ️ **Otomatik Kademeli Fallback Güvencesi**: `HF_TOKEN` girilmediğinde veya model erişim izni bulunmadığında sistem çökmez; otomatik olarak 2. Kademe (**SpeechBrain ECAPA-TDNN**) veya 3. Kademe (**Local Spectral Cluster**) motoruna geçerek analizi kesintisiz tamamlar.

## Kurulum ve Başlatma

### 1. Bağımlılıkların Yüklenmesi
```bash
# Sanal ortamı aktifleştirme
.\venv\Scripts\activate

# Paketi ve tüm bağımlılıkları yükleme
pip install -e .
```

### 2. API Sunucusunun Başlatılması (Uvicorn)
Aşağıdaki komutlardan herhangi biriyle Web API sunucusunu ve İnteraktif Arayüzü çalıştırabilirsiniz:

```bash
# Seçenek A: Doğrudan Uvicorn ile
uvicorn audio_analyzer.api.main:app --host 0.0.0.0 --port 8000 --reload

# Seçenek B: CLI Giriş Noktası ile (pip install -e . sonrası)
audio-analyzer-api

# Seçenek C: Python Modülü olarak
python -m audio_analyzer.api.main
```

Sunucu başladıktan sonra:
- **Web UI & İnteraktif Arayüz**: `http://localhost:8000/`
- **Swagger API Dokümantasyonu**: `http://localhost:8000/docs`

### 3. CLI Analiz Komutunun Çalıştırılması
```bash
python run_analysis.py --audio storage/raw/ornek_ses.wav
```

### 4. Testlerin Çalıştırılması
```bash
pytest
```

### 5. Rust PyO3 Native DSP Performans Modülü (Opsiyonel)
Sistem, Rust ile yazılmış C-hızında 0-latency DSP (resampling, VAD energy, cosine similarity) modülüne sahiptir (`native/` klasörü). 
Rust compiler (`cargo`) sisteminizde yüklüyse native modülü derleyebilirsiniz:

```bash
# Maturin aracını yükleyin ve Rust C-extension modülünü derleyin
pip install maturin
maturin develop --manifest-path native/Cargo.toml
```

*Not: Rust derlenmediğinde sistem otomatik olarak NumPy tabanlı Python fallback modülünü çalıştırır.*

