# Ses Analizi Sistemi (Speech-to-Text & Speaker Diarization)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

Yüksek performanslı, modüler, **Clean Architecture / Code-First** prensiplerine uygun olarak tasarlanmış ses analiz sistemi.

## Özellikler
- **Speech-to-Text (STT)**: Faster-Whisper ile zaman damgalı metne dönüştürme (`tiny`, `small`, `medium` model desteği).
- **%100 Çevrimdışı Speaker Diarization**:
  - **Birincil Motor**: SpeechBrain ECAPA-TDNN (%100 Çevrimdışı, Token-Free & Derin Nöral Ses Parmak İzi).
  - **İkincil Motor**: Local Spectral Clustering (Tamamen yerel akustik kümeleme).
- **SemanticRefiner & Yerel LLM Entegrasyonu**:
  - Alan Odaklı Kurallar (`domain_mode="call_center"` ile müşteri/temsilci geçiş tespiti ve rol sabitleme).
  - Opsiyonel yerel Ollama LLM (`llama3.2` / `qwen2.5`) entegrasyonu ile konuşmacı metinlerinin anlamsal iyileştirilmesi.
- **Fusion Engine**: IoU ve Midpoint çakışma çözümleme algoritması + 1.5s sessizlik eşiği.
- **Voice Activity Detection (VAD)**: Silero VAD ile gürültü ve sessizlik halüsinasyon filtrelemesi.
- **Rust PyO3 Native DSP Accelerator**: Rust ile yazılmış C-hızında sıfır gecikmeli resample, VAD ve kosinüs benzerliği modülü.
- **Asenkron Job Queue**: Redis Queue (RQ), Celery ve FastAPI BackgroundTasks ile non-blocking HTTP 202 istek işleme.
- **Sıcak Yükleme (Warm-Loading)**: Singleton AI Pipeline ile hızlı ve düşük gecikmeli analiz.

## 🏢 Kurumsal Çevrimdışı (Air-Gapped / Token-Free) Yapılandırma

Sistem, internete hiç çıkmadan ve **herhangi bir HuggingFace Token'ına ihtiyaç duymadan (Token-Free)** %100 yerel modda çalışır:

* **Çevrimdışı (Air-Gapped) Çalıştırma:** Modeller yerel diskinizdeki önbellekten veya `storage/models/` klasöründen okunur. Herhangi bir dış API veya HuggingFace token zorunluluğu yoktur.
* **Token-Free Diarization:** **SpeechBrain ECAPA-TDNN** ve **Local Spectral Cluster** diyarizasyon motorları tamamen yerel matematiksel vektör hesaplaması yapar ve internet/token gerektirmez.

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

---

## ⚡ CPU Verimliliği & Kapasite Planlaması

### 1. CPU Thread Bütçesi Kuralları
Sistemde CPU aşırı kullanımı (oversubscription) engellemek için thread bütçesi `WORKER_CPU_THREADS` ortam değişkeni ile yönetilir:

```bash
# Örnek: 8 Çekirdekli bir sunucuda 2 Worker çalıştırma
export WORKER_CPU_THREADS=4
```

**Kural:** `(worker_süreç_sayısı × WORKER_CPU_THREADS) <= toplam_çekirdek_sayısı`

### 2. Pipeline Profilleri (`PIPELINE_PROFILE`)
- **`feedback` Profil:** Kısa ve yüksek hacimli geri bildirim mesajları için optimize edilmiştir.
  - Diarization: Ses < `PIPELINE_MIN_DIARIZE_SEC` (varsayılan 10s) ise atlanır (`SPEAKER_00`).
  - Denoiser: Yalnızca ölçülen SNR < `PIPELINE_MIN_SNR_DB` (varsayılan 15 dB) ise çalışır.
  - SemanticRefiner: Yalnızca `DOMAIN_MODE` tanımlıysa çalışır.
  - Whisper Beam Size: 1.
- **`full` Profil (Varsayılan):** Tüm analiz adımlarını eksiksiz çalıştırır. Whisper Beam Size: 5.

### 3. Çevrimdışı Kapasite Hesaplama Formülü
Kapasite planlaması yapılırken aşağıdaki matematiksel formül esas alınır:

$$\text{Gereken Çekirdek Sayısı} = \frac{\text{Toplam Ses Süresi (sn)} \times k}{\text{Hedef Tamamlanma Süresi (sn)}}$$

> **Not:** $k$ katsayısı (ses saniyesi başına harcanan çekirdek-saniye), `scripts/benchmark_cpu.py` betiği çalıştırılarak donanım üzerinde ampirik olarak ölçülmelidir (tahmin yazılmaz).

### 4. CPU Performans Benchmark Betiği
```bash
python scripts/benchmark_cpu.py --audio-dir ./storage --models tiny,small --profiles feedback,full --threads 4
```



