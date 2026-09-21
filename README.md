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

## 🏢 Kurumsal Çevrimdışı (Air-Gapped / Token-Free) Yapılandırma

Sistem, internete hiç çıkmadan ve **herhangi bir HuggingFace Token'ına ihtiyaç duymadan (Token-Free)** %100 yerel modda çalışır:

* **Çevrimdışı (Air-Gapped) Çalıştırma:** Modeller yerel `storage/models/` klasöründen okunur. Herhangi bir dış API veya HuggingFace token zorunluluğu yoktur.
* **Token-Free Diarization:** 2. Kademe (**SpeechBrain ECAPA-TDNN**) ve 3. Kademe (**Local Spectral Cluster**) diyarizasyon motorları tamamen yerel matematiksel vektör hesaplaması yapar ve internet/token gerektirmez.
* *(Opsiyonel)* Çevrimiçi HuggingFace PyAnnote 3.1 kullanmak isterseniz `.env` dosyasında `HF_TOKEN` girebilirsiniz. Girilmediğinde sistem otomatik olarak %100 yerel çevrimdışı motorla devam eder.

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

---

## Veritabanı ve Alembic Migrasyon Stratejisi

Sistem, **Dialect-Agnostic SQLAlchemy ORM** ve **Alembic** entegrasyonu ile veritabanı şemalarını esnek şekilde yönetir:

- **Geliştirme / Yerel Ortam (Development & Test)**:
  `api/main.py` (FastAPI lifespan) ve `run_analysis.py` (CLI runner) yerel hızlı geliştirme için `Base.metadata.create_all(bind=engine)` yöntemini kullanır. Veritabanı dosyası (`dev_database.db`) yoksa otomatik oluşturulur.
- **Canlı / Staging Ortamı (Production / Staging Schema Management)**:
  Canlı ortamlarda veritabanı şemalarını versiyonlamak ve veri kaybı olmadan güncellemek için `alembic` kullanılır:

  ```bash
  # Canlı veritabanını en son migrasyon seviyesine yükseltme
  alembic upgrade head

  # Mevcut canlı veritabanı migrasyon durumunu kontrol etme
  alembic current

  # Modellerde yeni bir alan tanımlandığında otomatik migrasyon dosyası üretme
  alembic revision --autogenerate -m "Şema güncelleme açıklaması"
  ```


