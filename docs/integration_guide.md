# 🏢 Kurumsal Sistem Entegrasyonu & Webhook Kullanım Kılavuzu

Bu doküman, Ses Analizi Platformu'nun Türkiye genelindeki üçüncü parti sistemlere (Şehir Hastaneleri HBYS, Çağrı Merkezleri, CRM, ERP) REST API ve **Asenkron Webhook (Geri Bildirim)** ile nasıl entegre edileceğini açıklar.

---

## 1. 🌐 Çevrimdışı (Air-Gapped / On-Premises) Kurulum

Sistem internete hiç bağlanmadan tam çevrimdışı çalışabilir. Modeller sunucuya bir kez indirildikten sonra `HF_HUB_OFFLINE=1` modunda devreye alınır:

```bash
# 1. Modelleri tek seferlik yerel klasöre paketleyin
python scripts/download_offline_models.py

# 2. Çevrimdışı modda sunucuyu başlatın
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export WHISPER_MODEL_SIZE=small

uvicorn audio_analyzer.api.main:app --app-dir src --host 0.0.0.0 --port 8000
```

---

## 2. 📤 Analiz İsteği Gönderme (API Endpoint)

Dış sistemler ses analizi başlatmak için `POST /api/v1/analyze` servisini çağırır.

### İstek Parametreleri (Multipart Form Data):
* `file`: Ses Dosyası (MP3, WAV, FLAC, M4A, OGG)
* `callback_url` *(Opsiyonel)*: Analiz bittiğinde sonucun gönderileceği Webhook adresi.

### Örnek cURL İsteği:
```bash
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -F "file=@/path/to/hastane_cagri_kaydi.wav" \
  -F "callback_url=https://hbys.hastane.gov.tr/api/audio-callback"
```

### Dönüş Yanıtı (`HTTP 202 Accepted`):
```json
{
  "job_id": "7d972041-1744-4374-81eb-103a6fa303de",
  "file_name": "hastane_cagri_kaydi.wav",
  "status": "PENDING",
  "message": "Ses dosyası kabul edildi, analiz arka planda başlatıldı."
}
```

---

## 3. 🔔 Webhook (Callback) Geri Bildirim Yapısı

Analiz **COMPLETED** veya **FAILED** durumuna ulaştığında, sistem belirttiğiniz `callback_url` adresine otomatik bir `HTTP POST` bildirimi gönderir.

### Webhook Başlıkları (Headers):
```http
Content-Type: application/json; charset=utf-8
User-Agent: Antigravity-Audio-Analyzer-Webhook/1.0
X-Signature: 5a8d7e9f2b1a3c4d... (HMAC-SHA256 İmza Başlığı)
```

### Başarılı Analiz Payload Örneği (`COMPLETED`):
```json
{
  "job_id": "7d972041-1744-4374-81eb-103a6fa303de",
  "file_name": "hastane_cagri_kaydi.wav",
  "status": "COMPLETED",
  "language": "tr",
  "utterances": [
    {
      "speaker_id": "SPEAKER_00",
      "start_time": 0.5,
      "end_time": 3.2,
      "text": "Merhabalar, Şehir Hastanesi randevu hattına hoş geldiniz."
    },
    {
      "speaker_id": "SPEAKER_01",
      "start_time": 3.5,
      "end_time": 6.8,
      "text": "İyi günler, dahiliye polikliniginden randevu almak istiyorum."
    }
  ]
}
```

---

## 4. 🛡️ HMAC-SHA256 İmza Doğrulama (Güvenlik)

Dış sistemler gelen Webhook isteğinin gerçekten bu sunucudan geldiğini doğrulamak için `X-Signature` başlığını kontrolden geçirebilir:

```python
import hashlib, hmac

def verify_webhook(payload_bytes: bytes, received_signature: str, secret_key: str) -> bool:
    computed = hmac.new(secret_key.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, received_signature)
```
