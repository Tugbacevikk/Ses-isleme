import asyncio
import pytest

from audio_analyzer.workers.webhook_worker import run_webhook_worker_loop


@pytest.mark.asyncio
async def test_webhook_worker_loop_startup_with_sqlite(monkeypatch, tmp_path):
    """
    Webhook worker döngüsünün (run_webhook_worker_loop)
    TypeError fırlatmadan SQLite ortamında başlatılabildiğini ve
    0.3sn boyunca çökmeksizin çalıştığını doğrular.
    """
    db_file = tmp_path / "test_webhook_worker.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # Worker döngüsünü arka plan görevi olarak başlat
    worker_task = asyncio.create_task(run_webhook_worker_loop(poll_interval=0.1))

    # 0.3 saniye boyunca çökmeksizin çalıştığını bekle
    await asyncio.sleep(0.3)

    # Görevin çökmeyip hala çalışır durumda olduğunu doğrula
    assert not worker_task.done(), "Webhook worker task crashed unexpectedly on startup"

    # Görevi iptal et ve temizle
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
