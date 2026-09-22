"""
SQLite'tan PostgreSQL'e Veri Taşıma Betiği (Migration Script).
Tüm geçmiş ses kayıtlarını ve zaman damgalı konuşmacı cümlelerini
0 veri kaybı ile SQLite'tan PostgreSQL veritabanına aktarır.
"""
import os
import sys
from pathlib import Path

# Proje kök dizinini ekle
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audio_analyzer.adapters.repository.models import AudioRecordModel, Base, TranscriptUtteranceModel


def migrate():
    sqlite_url = os.getenv("SQLITE_DATABASE_URL", "sqlite:///storage/dev_database.db")
    postgres_url = os.getenv("DATABASE_URL")

    if not postgres_url or not postgres_url.startswith("postgres"):
        print(
            "[ERROR] DATABASE_URL ortam değişkeninde geçerli bir PostgreSQL adresi bulunamadı!\n"
            "Örnek: export DATABASE_URL=postgresql://kullanici:sifre@localhost:5432/ses_db"
        )
        return

    print(f"[START] SQLite ({sqlite_url}) -> PostgreSQL ({postgres_url}) Veri Taşıması Başlatılıyor...")

    try:
        sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
        postgres_engine = create_engine(postgres_url, pool_pre_ping=True)

        # PostgreSQL tablolarını güncel şema ile sıfırdan oluştur
        Base.metadata.create_all(postgres_engine)
        
        # PostgreSQL'de eksik kolonlar varsa ekle veya tabloları doğrula
        with postgres_engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE audio_records ADD COLUMN IF NOT EXISTS callback_url VARCHAR(1024);"))
            conn.execute(text("ALTER TABLE audio_records ADD COLUMN IF NOT EXISTS webhook_status VARCHAR(50);"))
            conn.commit()

        SqliteSession = sessionmaker(bind=sqlite_engine)
        PostgresSession = sessionmaker(bind=postgres_engine)

        sqlite_db = SqliteSession()
        postgres_db = PostgresSession()
    except Exception as init_err:
        print(f"[ERROR] Veritabanı bağlantı hatası: {init_err}")
        return

    try:
        records = sqlite_db.query(AudioRecordModel).all()
        print(f"[MIGRATE] Toplam {len(records)} adet ses kaydı inceleniyor...")

        migrated_records = 0
        migrated_utterances = 0

        for r in records:
            # PostgreSQL'de aynı ID ile kayıt var mı kontrol et
            existing = (
                postgres_db.query(AudioRecordModel)
                .filter(AudioRecordModel.id == r.id)
                .first()
            )
            if existing:
                continue

            new_record = AudioRecordModel(
                id=r.id,
                storage_uri=r.storage_uri,
                file_name=r.file_name,
                duration_seconds=r.duration_seconds,
                sample_rate=r.sample_rate,
                channels=r.channels,
                language=r.language,
                status=r.status,
                error_message=r.error_message,
                callback_url=r.callback_url,
                webhook_status=r.webhook_status,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            postgres_db.add(new_record)

            utterances = (
                sqlite_db.query(TranscriptUtteranceModel)
                .filter(TranscriptUtteranceModel.audio_record_id == r.id)
                .all()
            )
            for u in utterances:
                new_u = TranscriptUtteranceModel(
                    id=u.id,
                    audio_record_id=u.audio_record_id,
                    speaker_id=u.speaker_id,
                    start_time=u.start_time,
                    end_time=u.end_time,
                    text=u.text,
                    created_at=u.created_at,
                )
                postgres_db.add(new_u)
                migrated_utterances += 1

            migrated_records += 1

        postgres_db.commit()
        print(
            f"[DONE] Taşıma Tamamlandı! {migrated_records} ses kaydı, {migrated_utterances} cümle PostgreSQL'e aktarıldı."
        )

    except Exception as e:
        postgres_db.rollback()
        print(f"[ERROR] Veri taşıma hatası: {e}")
    finally:
        sqlite_db.close()
        postgres_db.close()


if __name__ == "__main__":
    migrate()
