"""常驻作业 Worker（规范 §5/§7/§19）：独立线程 + 独立事件循环，轮询 `job_executions`。

- 单实例即领导者（规范 §19.1：避免多实例重复执行）；多实例部署时需引入分布式锁。
- 进程重启后，`queued` 与到期 `retrying` 会自动继续；孤儿 `running` 由 runner 回收。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from aios.core.logging import get_logger, log_extra
from aios.modules.jobs import runner

logger = get_logger("aios.worker")


class JobWorker:
    """后台作业线程。start()/stop() 由应用生命周期调用。"""

    def __init__(self, *, poll_seconds: float = 0.5, batch: int = 5) -> None:
        self.poll_seconds = max(0.05, poll_seconds)
        self.batch = max(1, batch)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self.processed = 0

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aios-job-worker", daemon=True)
        self._thread.start()
        logger.info("worker_started", extra=log_extra(poll_seconds=self.poll_seconds))

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("worker_stopped", extra=log_extra(processed=self.processed))

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- 内部 ----
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._loop_forever())
        finally:
            try:
                loop.close()
            finally:
                self._loop = None

    async def _loop_forever(self) -> None:
        while not self._stop.is_set():
            try:
                done = await runner.run_once(limit=self.batch)
                self.processed += done
            except Exception as exc:  # noqa: BLE001 —— worker 循环不允许被单次异常打断
                logger.error("worker_tick_failed", exc_info=exc,
                             extra=log_extra(error_code=type(exc).__name__))
                done = 0
            await asyncio.sleep(0.05 if done else self.poll_seconds)


_worker: JobWorker | None = None


def get_worker(**kwargs: Any) -> JobWorker:
    global _worker
    if _worker is None:
        _worker = JobWorker(**kwargs)
    return _worker


def start_worker(**kwargs: Any) -> JobWorker:
    worker = get_worker(**kwargs)
    worker.start()
    return worker


def stop_worker() -> None:
    if _worker is not None:
        _worker.stop()
