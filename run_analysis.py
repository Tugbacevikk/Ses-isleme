import asyncio
import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Proje kaynak dizinini Python yoluna ekleme
sys.path.insert(0, str(Path(__file__).parent / "src"))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


from audio_analyzer.adapters.repository.models import Base
from audio_analyzer.adapters.repository.unit_of_work import SqlAlchemyUnitOfWork
from audio_analyzer.adapters.storage.storage_factory import get_storage_adapter
from audio_analyzer.api.dependencies import create_async_db_engine
from audio_analyzer.domain.models import DeviceConfig
from audio_analyzer.services.fusion_engine import FusionEngine
from audio_analyzer.services.job_service import JobService
from audio_analyzer.services.pipeline import AudioAnalysisPipeline


def create_synthetic_wav(file_path: str, duration_sec: float = 3.0):
    """
    Sistemi test etmek için 16kHz Mono 3 saniyelik bip tonlu sentetik test WAV dosyası üretir.
    """
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)      # Mono
        wav_file.setsampwidth(2)      # 16-bit (2 bytes)
        wav_file.setframerate(sample_rate)

        # 440 Hz Sinüs dalgası (A4 notası) üretme
        for i in range(num_samples):
            t = float(i) / sample_rate
            sample = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * t))
            data = struct.pack("<h", sample)
            wav_file.writeframesraw(data)

    print(f"  [+] Sentetik test ses dosyası oluşturuldu: {path.absolute()}")


async def main_async():
    print("=" * 80)
    print("      SES ANALİZİ SİSTEMİ - MÜHENDİSLİK ÇALIŞTIRMA BETİĞİ (RUNNER)")
    print("=" * 80)

    # 1. Donanım Sezgisel Seçimi (GPU vs CPU)
    device_config = DeviceConfig()
    print(f"\n[1/5] DONANIM VE CİHAZ YAPILANDIRMASI:")
    print(f"      - Algılanan Donanım (Device) : {device_config.device.upper()}")
    print(f"      - Hassasiyet (Compute Type)  : {device_config.compute_type}")
    print(f"      - GPU İndeksi               : {device_config.device_index}")

    # 2. Veritabanı ve UoW Kurulumu
    database_url = os.getenv("DATABASE_URL", "sqlite:///storage/dev_database.db")
    engine = create_async_db_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=AsyncSession)
    uow = SqlAlchemyUnitOfWork(session_factory=session_factory)
    print(f"\n[2/5] VERİTABANI İŞLEMLERİ (Unit-of-Work):")
    print(f"      - Veritabanı URL           : {database_url}")
    print(f"      - Veritabanı Tabloları      : audio_records, transcript_utterances [HAZIR]")

    # 3. Ses Dosyası Hazırlığı
    target_audio_file = "storage/raw/demo_sample.wav"
    
    if len(sys.argv) > 1 and sys.argv[1] != "--demo":
        target_audio_file = sys.argv[1]
        if not os.path.exists(target_audio_file):
            print(f"\n  [!] HATA: Belirtilen ses dosyası bulunamadı: {target_audio_file}")
            sys.exit(1)
        print(f"\n[3/5] SES DOSYASI:")
        print(f"      - Kullanıcı Ses Dosyası     : {target_audio_file}")
    else:
        print(f"\n[3/5] DEMO TEST MODU AKTİF:")
        create_synthetic_wav(target_audio_file, duration_sec=3.0)

    with open(target_audio_file, "rb") as f:
        audio_bytes = f.read()

    # 4. Modül ve Adaptörlerin Başlatılması (Clean Architecture)
    print(f"\n[4/5] SİSTEM ADAPTÖRLERİ BİRLEŞTİRİLİYOR (Clean Architecture):")
    storage = get_storage_adapter()

    # 4.1 STT Engine (FasterWhisper)
    try:
        from audio_analyzer.adapters.stt.faster_whisper_adapter import FasterWhisperAdapter
        stt_engine = FasterWhisperAdapter(model_size="small", device_config=device_config)
        print("      - STT Engine (FasterWhisper): [GERÇEK GERÇEK ZAMANLI AI MODELİ AKTİF - Small Model]")
    except Exception as e:
        allow_mock = os.getenv("ALLOW_MOCK_STT", "false").lower() == "true"
        if allow_mock:
            print(f"      - STT Engine               : [DEMO MOCK STT AKTİF - ALLOW_MOCK_STT=true - {e}]")
            from audio_analyzer.adapters.stt.mock_stt_adapter import MockSTTAdapter
            stt_engine = MockSTTAdapter()
        else:
            raise RuntimeError(f"STT Motoru (FasterWhisper) yüklenemedi: {e}. Lütfen faster-whisper bağımlılığını veya ALLOW_MOCK_STT=true ayarını kontrol edin.")

    # 4.2 Diarization Engine
    try:
        from audio_analyzer.adapters.diarization.speechbrain_adapter import SpeechBrainECAPADiarizer
        diarizer = SpeechBrainECAPADiarizer(device_config=device_config)
        print("      - Diarizer                 : [SPEECHBRAIN ECAPA-TDNN DERİN SİNİR AĞI AKTİF (%100 ÇEVRİMDİŞİ)]")
    except Exception as e:
        from audio_analyzer.adapters.diarization.cluster_diarizer import LocalSpectralClusterDiarizer
        diarizer = LocalSpectralClusterDiarizer(device_config=device_config)
        print(f"      - Diarizer                 : [YEREL AKUSTİK KÜMELEYİCİ AKTİF - {e}]")

    from audio_analyzer.adapters.audio.rust_dsp_adapter import RustAudioDSPProcessor
    audio_processor = RustAudioDSPProcessor()
    if audio_processor.using_rust:
        print("      - Audio DSP                : [RUST PyO3 NATIVE NATIVE_AUDIO_DSP C-EXTENSION AKTİF]")
    else:
        print("      - Audio DSP                : [PYTHON NUMPY FALLBACK AKTİF]")

    pipeline = AudioAnalysisPipeline(
        stt_engine=stt_engine,
        diarizer=diarizer,
        audio_processor=audio_processor,
        fusion_engine=FusionEngine(max_silence_threshold=3.0),
    )

    # 5. Görev Oluşturma ve Yürütme (UnitOfWork Context Manager)
    print(f"\n[5/5] SES ANALİZ GÖREVİ ÇALIŞTIRILIYOR (UoW):")
    filename = Path(target_audio_file).name

    async with uow:
        job_service = JobService(
            storage=storage,
            repository=uow.repository,
            pipeline=pipeline,
        )

        job_id = await job_service.create_job(file_name=filename, file_bytes=audio_bytes)
        print(f"      - Oluşturulan İş ID (job_id): {job_id} [Durum: PENDING]")

        print(f"      - Worker Görevi Yürütülüyor...")
        success = await job_service.execute_job(job_id)

        if success:
            record = await uow.repository.get_record_by_id(job_id)
            print("\n" + "=" * 80)
            print("                        ANALİZ BAŞARIYLA TAMAMLANDI!")
            print("=" * 80)
            print(f"  * Kayıt ID         : {record.id}")
            print(f"  * Dosya Adı        : {record.file_name}")
            print(f"  * Tespit Edilen Dil: {record.language or 'tr'}")
            print(f"  * Durum            : {record.status.value}")
            print(f"  * Konuşmacı Bloğu  : {len(record.utterances)} Adet Utterance\n")

            print("--- KONUŞMACI VE ZAMAN DAMGALI METİN ÇIKTISI ---")
            out_list = []
            for u in record.utterances:
                time_str = f"[{u.start_time:05.2f}s - {u.end_time:05.2f}s]"
                print(f"  {time_str} {u.speaker_id:12s} : {u.text}")
                out_list.append({
                    "speaker": u.speaker_id,
                    "start": u.start_time,
                    "end": u.end_time,
                    "text": u.text
                })

            # JSON çıktısını dışa aktarma
            json_output_path = Path("storage/processed/analysis_result.json")
            json_output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_output_path, "w", encoding="utf-8") as jf:
                json.dump(out_list, jf, ensure_ascii=False, indent=2)

            print(f"\n  [+] Detaylı JSON çıktısı kaydedildi: {json_output_path.absolute()}")
            print("=" * 80 + "\n")
        else:
            record = await uow.repository.get_record_by_id(job_id)
            print(f"\n  [!] HATA: Analiz başarısız oldu! Durum: {record.status.value}")
            print(f"  [!] Detay: {record.error_message}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

