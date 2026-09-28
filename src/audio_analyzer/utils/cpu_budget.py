"""
CPU Thread Bütçesi Yapılandırma Modülü.
Worker başlangıcında veya model yüklemede tek bir noktadan:
- WORKER_CPU_THREADS env değişkenini okur (varsayılan: min(4, cpu_count)).
- CTranslate2 (faster-whisper), OpenMP, MKL, OpenBLAS ve PyTorch thread bütçelerini sınırlar.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def setup_cpu_thread_budget(threads: Optional[int] = None) -> int:
    """
    Tüm kütüphanelerin (Torch, OpenMP, MKL, OpenBLAS, faster-whisper)
    CPU thread sayılarını tek noktadan yapılandırır.
    Döner: Yapılandırılan thread sayısı
    """
    if threads is None:
        env_val = os.getenv("WORKER_CPU_THREADS") or os.getenv("WHISPER_CPU_THREADS")
        if env_val:
            try:
                threads = int(env_val)
            except ValueError:
                threads = None

    if threads is None or threads <= 0:
        cpu_cnt = os.cpu_count() or 4
        threads = min(4, max(1, cpu_cnt))

    threads_str = str(threads)
    os.environ["WORKER_CPU_THREADS"] = threads_str
    os.environ["WHISPER_CPU_THREADS"] = threads_str
    os.environ["OMP_NUM_THREADS"] = threads_str
    os.environ["MKL_NUM_THREADS"] = threads_str
    os.environ["OPENBLAS_NUM_THREADS"] = threads_str
    os.environ["VECLIB_MAXIMUM_THREADS"] = threads_str
    os.environ["NUMEXPR_NUM_THREADS"] = threads_str

    try:
        import torch

        torch.set_num_threads(threads)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(min(2, threads))
    except Exception:
        pass

    logger.info("CPU thread bütçesi yapılandırıldı: WORKER_CPU_THREADS=%d", threads)
    return threads
