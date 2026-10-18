"""Contexto de execução passado às etapas do pipeline (progresso, cancelamento, log)."""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable

from .errors import Cancelled


class JobContext:
    def __init__(
        self,
        project_id: str,
        on_progress: Callable[[str, float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.project_id = project_id
        self._on_progress = on_progress
        self._is_cancelled = is_cancelled or (lambda: False)
        self.log = logger or logging.getLogger(f"clipflow.{project_id}")
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self._span = (0.0, 1.0)
        self.stage = ""

    # --- progresso -------------------------------------------------------
    def span(self, start: float, end: float, stage: str) -> "JobContext":
        """Define a faixa do progresso global usada pelas próximas chamadas de progress()."""
        self._span = (start, end)
        self.stage = stage
        self.progress(0.0)
        return self

    def progress(self, frac: float) -> None:
        frac = min(max(frac, 0.0), 1.0)
        a, b = self._span
        if self._on_progress:
            self._on_progress(self.stage, a + (b - a) * frac)

    # --- cancelamento ----------------------------------------------------
    def cancelled(self) -> bool:
        return bool(self._is_cancelled())

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def register(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(proc)

    def unregister(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(proc)

    def kill_processes(self) -> None:
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.kill()
            except OSError:
                pass


def null_context(project_id: str = "000000000000") -> JobContext:
    return JobContext(project_id)
