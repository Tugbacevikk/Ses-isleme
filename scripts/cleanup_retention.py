#!/usr/bin/env python3
"""
Veri Saklama ve Temizlik Betiği (Retention & Cleanup Script).
Süresi dolan ham ses dosyalarını (AUDIO_RETENTION_HOURS) ve veritabanı kayıtlarını (RESULT_RETENTION_DAYS) temizler.

Kullanım:
    python scripts/cleanup_retention.py --retention-hours 24 --retention-days 30
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audio_analyzer.adapters.storage.storage_factory import get_storage_adapter
from audio_analyzer.api.dependencies import create_async_db_engine, get_uow_with_engine
from audio_analyzer.services.retention_service import RetentionService


async def run_cleanup(retention_hours: int, retention_days: int):
    print("=================================================================")
    print("             VERİ SAKLAMA & TEMİZLİK ÇALIŞTIRILIYOR")
    print(f" Audio Retention: {retention_hours} saat | Result Retention: {retention_days} gün")
    print("=================================================================\n")

    engine = create_async_db_engine()
    storage = get_storage_adapter()

    async with get_uow_with_engine(engine) as uow:
        ret_svc = RetentionService(storage=storage, repository=uow.repository)

        audio_cleaned = await ret_svc.cleanup_expired_audio_files(retention_hours=retention_hours)
        records_cleaned = await ret_svc.cleanup_old_database_records(retention_days=retention_days)

        print(f" -> Temizlenen Ham Ses Dosyası Sayısı: {audio_cleaned}")
        print(f" -> Temizlenen Veritabanı Kayıt Sayısı: {records_cleaned}")

    await engine.dispose()
    print("\nTemizlik başarıyla tamamlandı.")


def main():
    parser = argparse.ArgumentParser(description="Veri Saklama Temizlik Betiği")
    parser.add_argument("--retention-hours", type=int, default=24, help="Ham ses dosyaları saklama süresi (saat)")
    parser.add_argument("--retention-days", type=int, default=30, help="Veritabanı sonuç kayıtları saklama süresi (gün)")

    args = parser.parse_args()
    asyncio.run(run_cleanup(args.retention_hours, args.retention_days))


if __name__ == "__main__":
    main()
