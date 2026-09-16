import uuid
import os
from typing import Dict, Any, List
from dotenv import load_dotenv

# .env dosyasındaki ortam değişkenlerini yükle (Örn: HF_TOKEN)
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.postgres_repository import PostgresRepository
from audio_analyzer.adapters.storage.local_storage_adapter import LocalStorageAdapter
from audio_analyzer.services.pipeline import AudioAnalysisPipeline
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.job_service import JobService
from audio_analyzer.domain.models import DeviceConfig, JobStatus

# FastAPI Uygulaması
app = FastAPI(
    title="Ses Analizi Platformu (STT + Speaker Diarization)",
    description="Gelişmiş Ses Analizi ve Konuşmacı Ayrıştırma Platformu Web Arayüzü",
    version="1.0.0",
)

# SQLite/PostgreSQL DB Bağlantısı
DATABASE_URL = "sqlite:///storage/dev_database.db"
engine = create_engine(DATABASE_URL, echo=False)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Response Schemas
class JobCreateResponse(BaseModel):
    job_id: str
    file_name: str
    status: str
    message: str


class UtteranceResponse(BaseModel):
    speaker_id: str
    start_time: float
    end_time: float
    text: str


class JobStatusResponse(BaseModel):
    job_id: str
    file_name: str
    status: str
    language: str | None = None
    error_message: str | None = None
    utterances: List[UtteranceResponse] = []


# Modern, Premium Glassmorphism Web Arayüzü (Ana Sayfa)
HTML_UI = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ses Analizi Platformu | STT & Konuşmacı Algılama</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-card: rgba(30, 41, 59, 0.7);
            --border-card: rgba(255, 255, 255, 0.1);
            --accent-purple: #8b5cf6;
            --accent-blue: #3b82f6;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Outfit', sans-serif;
        }

        body {
            background-color: var(--bg-primary);
            background-image: 
                radial-gradient(at 0% 0%, rgba(139, 92, 246, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.15) 0px, transparent 50%);
            color: var(--text-main);
            min-height: 100vh;
            padding: 2rem 1rem;
            display: flex;
            justify-content: center;
        }

        .container {
            width: 100%;
            max-width: 900px;
        }

        /* Header Styling */
        header {
            text-align: center;
            margin-bottom: 2.5rem;
        }

        .logo-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(139, 92, 246, 0.15);
            border: 1px solid rgba(139, 92, 246, 0.3);
            padding: 0.4rem 1rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 500;
            color: #c4b5fd;
            margin-bottom: 1rem;
        }

        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }

        p.subtitle {
            color: var(--text-muted);
            font-size: 1.125rem;
        }

        /* Glassmorphism Card */
        .glass-card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 1.5rem;
            padding: 2rem;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            margin-bottom: 2rem;
        }

        /* Upload Zone */
        .upload-zone {
            border: 2px dashed rgba(139, 92, 246, 0.4);
            border-radius: 1rem;
            padding: 3rem 1.5rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            background: rgba(15, 23, 42, 0.4);
        }

        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--accent-purple);
            background: rgba(139, 92, 246, 0.1);
            transform: translateY(-2px);
        }

        .upload-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            display: block;
        }

        .btn-upload {
            background: linear-gradient(135deg, var(--accent-purple) 0%, var(--accent-blue) 100%);
            color: white;
            border: none;
            padding: 0.75rem 2rem;
            border-radius: 0.75rem;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 1rem;
            box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
        }

        .btn-upload:hover {
            opacity: 0.95;
            transform: scale(1.02);
        }

        input[type="file"] {
            display: none;
        }

        /* Progress & Status */
        .status-container {
            display: none;
            margin-top: 1.5rem;
            text-align: center;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid rgba(255, 255, 255, 0.1);
            border-left-color: var(--accent-purple);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 1rem;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Results Container */
        #resultsSection {
            display: none;
        }

        .meta-bar {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border-card);
        }

        .meta-item {
            background: rgba(15, 23, 42, 0.6);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            font-size: 0.875rem;
            color: var(--text-muted);
        }

        .meta-item strong {
            color: var(--text-main);
        }

        /* Transcript Utterances */
        .utterance-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .utterance-card {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 0.75rem;
            padding: 1.25rem;
            transition: all 0.2s ease;
        }

        .utterance-card:hover {
            border-color: rgba(139, 92, 246, 0.3);
            background: rgba(30, 41, 59, 0.8);
        }

        .speaker-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .speaker-badge {
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .speaker-badge.spk-0 {
            background: rgba(139, 92, 246, 0.2);
            color: #c4b5fd;
            border: 1px solid rgba(139, 92, 246, 0.4);
        }

        .speaker-badge.spk-1 {
            background: rgba(6, 182, 212, 0.2);
            color: #67e8f9;
            border: 1px solid rgba(6, 182, 212, 0.4);
        }

        .time-badge {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-family: monospace;
        }

        .utterance-text {
            font-size: 1rem;
            line-height: 1.6;
            color: #e2e8f0;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-badge">
                <span>🎙️</span> Ses Analizi Engine v1.0
            </div>
            <h1>Ses Analizi ve Konuşmacı Algılama</h1>
            <p class="subtitle">Ses dosyanızı yükleyin; yapay zeka kimin ne zaman konuştuğunu otomatik metne döksün.</p>
        </header>

        <!-- Yükleme Kartı -->
        <div class="glass-card">
            <div class="upload-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
                <span class="upload-icon">📁</span>
                <h3>Ses Dosyanızı Sürükleyin veya Seçin</h3>
                <p style="color: var(--text-muted); margin-top: 0.5rem; font-size: 0.875rem;">
                    Desteklenen Formatlar: MP3, WAV, FLAC, M4A, OGG
                </p>
                <button class="btn-upload" type="button">Dosya Seç</button>
                <input type="file" id="fileInput" accept="audio/*" onchange="handleFileSelect(event)">
            </div>

            <!-- Durum Göstergesi -->
            <div class="status-container" id="statusContainer">
                <div class="spinner"></div>
                <h4 id="statusTitle">Ses Analiz Ediliyor...</h4>
                <p id="statusDesc" style="color: var(--text-muted); font-size: 0.875rem; margin-top: 0.25rem;">
                    Yapay zeka ses kaydını işliyor ve konuşmacıları ayrıştırıyor. Lütfen bekleyin...
                </p>
            </div>
        </div>

        <!-- Analiz Sonuçları Kartı -->
        <div class="glass-card" id="resultsSection">
            <h2 style="margin-bottom: 1rem; font-size: 1.5rem;">Analiz Sonuçları</h2>
            
            <div class="meta-bar">
                <div class="meta-item">Dosya: <strong id="metaFileName">-</strong></div>
                <div class="meta-item">Tespit Edilen Dil: <strong id="metaLanguage">-</strong></div>
                <div class="meta-item">Paragraf / Konuşmacı Bloğu: <strong id="metaBlockCount">-</strong></div>
            </div>

            <div class="utterance-list" id="utteranceList">
                <!-- Dinamik Cümle Kartları Buraya Gelecek -->
            </div>
        </div>
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const statusContainer = document.getElementById('statusContainer');
        const resultsSection = document.getElementById('resultsSection');
        const utteranceList = document.getElementById('utteranceList');

        // Drag & Drop
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                uploadFile(e.dataTransfer.files[0]);
            }
        });

        function handleFileSelect(e) {
            if (e.target.files.length > 0) {
                uploadFile(e.target.files[0]);
            }
        }

        async function uploadFile(file) {
            statusContainer.style.display = 'block';
            resultsSection.style.display = 'none';

            const formData = new FormData();
            formData.append('file', file);

            try {
                // 1. POST /api/v1/analyze
                const response = await fetch('/api/v1/analyze', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error('Dosya yükleme başarısız!');
                }

                const data = await response.json();
                const jobId = data.job_id;

                // 2. Poll GET /api/v1/jobs/{jobId}
                pollJobStatus(jobId);

            } catch (error) {
                alert('Hata: ' + error.message);
                statusContainer.style.display = 'none';
            }
        }

        async function pollJobStatus(jobId) {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/v1/jobs/${jobId}`);
                    const job = await res.json();

                    if (job.status === 'COMPLETED') {
                        clearInterval(interval);
                        statusContainer.style.display = 'none';
                        renderResults(job);
                    } else if (job.status === 'FAILED') {
                        clearInterval(interval);
                        statusContainer.style.display = 'none';
                        alert('Analiz Başarısız Oldu: ' + (job.error_message || 'Bilinmeyen hata'));
                    }
                } catch (e) {
                    console.error(e);
                }
            }, 1000);
        }

        let currentJobId = null;
        let currentJobData = null;

        function renderResults(job) {
            currentJobId = job.job_id;
            currentJobData = job;
            document.getElementById('metaFileName').textContent = job.file_name;
            document.getElementById('metaLanguage').textContent = (job.language || 'tr').toUpperCase();
            document.getElementById('metaBlockCount').textContent = job.utterances.length + ' Adet';

            utteranceList.innerHTML = '';

            job.utterances.forEach((u, index) => {
                const card = document.createElement('div');
                card.className = 'utterance-card';

                const isSpk0 = u.speaker_id.includes('00') || u.speaker_id.includes('0');
                const badgeClass = isSpk0 ? 'spk-0' : 'spk-1';

                const startStr = formatTime(u.start_time);
                const endStr = formatTime(u.end_time);

                card.innerHTML = `
                    <div class="speaker-header">
                        <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                            <span class="speaker-badge ${badgeClass}">${u.speaker_id}</span>
                            <label style="font-size: 0.8rem; color: #94a3b8; font-weight: 500;">Konuşmacı Ataması:</label>
                            <select class="speaker-select" style="background: #0f172a; color: #38bdf8; border: 1px solid #38bdf8; padding: 0.35rem 0.75rem; border-radius: 0.5rem; font-weight: 600; cursor: pointer; font-size: 0.85rem;" onchange="updateSpeaker('${job.job_id}', ${index}, this.value)">
                                <option value="SPEAKER_00" ${u.speaker_id === 'SPEAKER_00' ? 'selected' : ''}>SPEAKER_00 (Müşteri Temsilcisi)</option>
                                <option value="SPEAKER_01" ${u.speaker_id === 'SPEAKER_01' ? 'selected' : ''}>SPEAKER_01 (Müşteri)</option>
                                <option value="SPEAKER_02" ${u.speaker_id === 'SPEAKER_02' ? 'selected' : ''}>SPEAKER_02 (Diğer)</option>
                            </select>
                        </div>
                        <span class="time-badge">[${startStr} - ${endStr}]</span>
                    </div>
                    <div id="text-${index}" class="utterance-text" contenteditable="true" style="outline: 1px dashed rgba(139, 92, 246, 0.5); padding: 0.75rem; border-radius: 0.5rem; background: rgba(15, 23, 42, 0.6); margin-top: 0.5rem; min-height: 40px;" onblur="updateText('${job.job_id}', ${index}, '${u.speaker_id}', this.innerText)">${u.text}</div>
                    <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem; justify-content: flex-end;">
                        <button style="background: rgba(139, 92, 246, 0.2); color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.4); padding: 0.35rem 0.85rem; border-radius: 0.375rem; font-size: 0.75rem; font-weight: 600; cursor: pointer;" onclick="saveCardEdits('${job.job_id}', ${index})">💾 Değişikliği Kaydet</button>
                    </div>
                `;
                utteranceList.appendChild(card);
            });

            resultsSection.style.display = 'block';
        }

        async function updateSpeaker(jobId, index, newSpeaker) {
            const textElem = document.getElementById(`text-${index}`);
            const text = textElem ? textElem.innerText : '';
            try {
                await fetch(`/api/v1/jobs/${jobId}/utterances/${index}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ speaker_id: newSpeaker, text: text })
                });
                alert('Konuşmacı atanması başarıyla güncellendi!');
            } catch (err) {
                console.error(err);
            }
        }

        async function updateText(jobId, index, speakerId, newText) {
            try {
                await fetch(`/api/v1/jobs/${jobId}/utterances/${index}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ speaker_id: speakerId, text: newText })
                });
            } catch (err) {
                console.error(err);
            }
        }

        async function saveCardEdits(jobId, index) {
            const textElem = document.getElementById(`text-${index}`);
            const selectElem = document.querySelectorAll('.speaker-select')[index];
            if (textElem && selectElem) {
                await fetch(`/api/v1/jobs/${jobId}/utterances/${index}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ speaker_id: selectElem.value, text: textElem.innerText })
                });
                alert('Değişiklikler başarıyla kaydedildi!');
            }
        }

        function formatTime(seconds) {
            const mins = Math.floor(seconds / 60);
            const secs = (seconds % 60).toFixed(2);
            return `${mins.toString().padStart(2, '0')}:${secs.padStart(5, '0')}s`;
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def get_web_ui():
    """
    Sürükle-Bırak Kolay Ses Analiz Web Arayüzü.
    http://localhost:8000/ adresinde doğrudan açılır.
    """
    return HTMLResponse(content=HTML_UI)


@app.post("/api/v1/analyze", response_model=JobCreateResponse, status_code=202)
async def upload_and_analyze_audio(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Ses dosyasını (MP3, WAV, FLAC) yükler, depolamaya kaydeder ve analiz görevini başlatır.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Ses dosyası adı boş olamaz.")

    file_bytes = await file.read()
    
    storage = LocalStorageAdapter(base_dir="storage/raw")
    repository = PostgresRepository(session=db)
    
    # 1. STT Engine (FasterWhisper)
    try:
        import faster_whisper
        from audio_analyzer.adapters.stt.faster_whisper_adapter import FasterWhisperAdapter
        stt_engine = FasterWhisperAdapter(model_size="small")
    except ImportError:
        from tests.system.test_full_pipeline import MockSTTEngine
        stt_engine = MockSTTEngine()

    # 2. Diarization Engine (PyAnnote 3.1 SOTA / SpeechBrain ECAPA-TDNN Fallback)
    hf_token = os.getenv("HF_TOKEN")
    diarizer = None
    if hf_token:
        try:
            from audio_analyzer.adapters.diarization.pyannote_adapter import PyAnnoteAdapter
            diarizer = PyAnnoteAdapter(auth_token=hf_token, device_config=DeviceConfig())
        except Exception as e:
            print(f"PyAnnoteAdapter note: {e}. Falling back to SpeechBrain ECAPA-TDNN.")

    if diarizer is None:
        try:
            from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer
            diarizer = SpeechBrainECAPADiarizer(device_config=DeviceConfig())
        except Exception as e:
            from audio_analyzer.adapters.diarization.cluster_diarizer import LocalSpectralClusterDiarizer
            diarizer = LocalSpectralClusterDiarizer(device_config=DeviceConfig())





    from audio_analyzer.adapters.audio.audio_converter import AudioConverterProcessor
    from audio_analyzer.adapters.audio.silero_vad import SileroVADProcessor
    from audio_analyzer.services.semantic_refiner import SemanticRefiner

    audio_processor = AudioConverterProcessor()

    pipeline = AudioAnalysisPipeline(
        stt_engine=stt_engine,
        diarizer=diarizer,
        audio_processor=audio_processor,
        vad_processor=SileroVADProcessor(),
        fusion_engine=FusionEngine(max_silence_threshold=3.0),
        semantic_refiner=SemanticRefiner(),
    )

    job_service = JobService(storage=storage, repository=repository, pipeline=pipeline)

    job_id = job_service.create_job(file_name=file.filename, file_bytes=file_bytes)

    # İşlemi yürüt
    job_service.execute_job(job_id)

    return JobCreateResponse(
        job_id=str(job_id),
        file_name=file.filename,
        status="PROCESSING",
        message="Ses analizi görevi başarıyla oluşturuldu.",
    )


class UtteranceUpdateRequest(BaseModel):
    speaker_id: str
    text: str


@app.put("/api/v1/jobs/{job_id}/utterances/{utterance_index}")
def update_utterance_speaker(
    job_id: str,
    utterance_index: int,
    req: UtteranceUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Kullanıcının Arayüzden (UI) manuel olarak konuşmacı etiketini veya metni değiştirmesini sağlar.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    repository = PostgresRepository(session=db)
    record = repository.get_record_by_id(record_uuid)

    if not record or not record.utterances:
        raise HTTPException(status_code=404, detail="Ses görevi veya cümleler bulunamadı.")

    if utterance_index < 0 or utterance_index >= len(record.utterances):
        raise HTTPException(status_code=400, detail="Geçersiz cümle indeksi.")

    record.utterances[utterance_index].speaker_id = req.speaker_id
    record.utterances[utterance_index].text = req.text
    db.commit()

    return {"status": "SUCCESS", "message": "Konuşmacı etiketi başarıyla güncellendi."}


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Verilen job_id görevinin durumunu ve analiz sonuçlarını getirir.
    """
    try:
        record_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz UUID formatı.")

    repository = PostgresRepository(session=db)
    record = repository.get_record_by_id(record_uuid)

    if not record:
        raise HTTPException(status_code=404, detail="Ses analizi görevi bulunamadı.")

    utterances = [
        UtteranceResponse(
            speaker_id=u.speaker_id,
            start_time=u.start_time,
            end_time=u.end_time,
            text=u.text,
        )
        for u in record.utterances
    ]

    return JobStatusResponse(
        job_id=str(record.id),
        file_name=record.file_name,
        status=record.status.value,
        language=record.language,
        error_message=record.error_message,
        utterances=utterances,
    )
