# Ses Analizi Sistemi (Speech-to-Text & Speaker Diarization)

Yüksek performanslı, modüler, **Clean Architecture / Code-First** prensiplerine uygun olarak tasarlanmış ses analiz sistemi.

## Özellikler
- **Speech-to-Text (STT)**: Faster-Whisper ile zaman damgalı metne dönüştürme.
- **Speaker Diarization**: PyAnnote 3.1 & SpeechBrain ECAPA-TDNN ile %100 çevrimdışı konuşmacı ayrıştırma.
- **Fusion Engine**: IoU ve Midpoint çakışma çözümleme algoritması + 1.5s Sessizlik eşiği.
- **Voice Activity Detection (VAD)**: Silero VAD ile gürültü ve sessizlik halüsinasyon filtrelemesi.
- **Asenkron Job Queue**: Redis + Celery ve FastAPI BackgroundTasks ile non-blocking HTTP 202 istek işleme.
- **Sıcak Yükleme (Warm-Loading)**: Singleton AI Pipeline ile hızlı ve düşük gecikmeli analiz.

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
