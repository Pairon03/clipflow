"""Fila de processamento local com estado persistido no SQLite.

- Tarefas sobrevivem a reinícios: as que estavam "running" voltam para "queued".
- Limite de tarefas simultâneas (config limits.max_concurrent_jobs).
- Tentativas controladas com espera crescente (apenas erros recuperáveis).
- Cancelamento: marca a tarefa e encerra imediatamente os processos FFmpeg.
- Um projeto nunca tem duas tarefas ativas ao mesmo tempo.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback

from . import config, db, storage
from .pipeline import runner
from .pipeline.context import JobContext
from .pipeline.errors import Cancelled, PipelineError

log = logging.getLogger("clipflow.worker")

ACTIVE = ("queued", "running")


class Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self._running: dict[int, JobContext] = {}
        self._lock = threading.Lock()
        self._dispatcher: threading.Thread | None = None

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        recovered = db.execute("UPDATE jobs SET status = 'queued', stage = 'Retomando após reinício' "
                               "WHERE status = 'running'")
        if recovered:
            log.info("%s tarefa(s) retomada(s) após reinício", recovered)
        self._stop.clear()
        self._dispatcher = threading.Thread(target=self._loop, name="clipflow-dispatcher", daemon=True)
        self._dispatcher.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            for ctx in self._running.values():
                ctx.kill_processes()
        if self._dispatcher:
            self._dispatcher.join(timeout)
        for t in self._threads:
            t.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    # ------------------------------------------------------------ API
    def enqueue(self, project_id: str, kind: str, payload: dict | None = None) -> int:
        import json

        existing = db.fetch_one("SELECT id FROM jobs WHERE project_id = ? AND status IN ('queued','running')",
                                (project_id,))
        if existing:
            raise ValueError("Este projeto já tem uma tarefa em andamento")
        job_id = db.execute(
            "INSERT INTO jobs (project_id, kind, payload_json, status, max_attempts, created_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?)",
            (project_id, kind, json.dumps(payload or {}), int(config.get("limits.max_attempts")), db.now()),
        )
        db.update("projects", project_id, status="queued", stage="Na fila", error=None,
                  progress=0 if kind == "analyze" else 0)
        self.wake()
        return job_id

    def cancel_project(self, project_id: str) -> bool:
        jobs = db.fetch_all("SELECT id, status FROM jobs WHERE project_id = ? AND status IN ('queued','running') "
                            "AND cancel_requested = 0", (project_id,))
        running = False
        for j in jobs:
            if j["status"] == "queued":
                db.update("jobs", j["id"], status="cancelled", finished_at=db.now(), stage="Cancelado")
            else:
                running = True
                db.update("jobs", j["id"], cancel_requested=1)
                with self._lock:
                    ctx = self._running.get(j["id"])
                if ctx:
                    ctx.kill_processes()
        if jobs:
            if running:  # a tarefa em execução marca o projeto como cancelado ao encerrar
                db.update("projects", project_id, stage="Cancelando…")
            else:
                db.update("projects", project_id, status="cancelled", stage="Cancelado pelo usuário")
        return bool(jobs)

    def stats(self) -> dict:
        with self._lock:
            running = list(self._running.keys())
        queued = db.fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'")["n"]
        return {"running": len(running), "queued": queued,
                "max_concurrent": int(config.get("limits.max_concurrent_jobs"))}

    # ------------------------------------------------------------ execução
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._dispatch()
            except Exception:  # nunca deixa o despachante morrer
                log.exception("Erro no despachante da fila")
            self._wake.wait(1.0)
            self._wake.clear()

    def _dispatch(self) -> None:
        self._threads = [t for t in self._threads if t.is_alive()]
        limit = max(1, int(config.get("limits.max_concurrent_jobs")))
        while len(self._threads) < limit and not self._stop.is_set():
            with self._lock:
                busy = set(self._running.keys())
            job = db.fetch_one(
                "SELECT * FROM jobs WHERE status = 'queued' AND run_after <= ? "
                "AND project_id NOT IN (SELECT project_id FROM jobs WHERE status = 'running') "
                "ORDER BY created_at LIMIT 1", (time.time(),))
            if not job or job["id"] in busy:
                return
            db.update("jobs", job["id"], status="running", started_at=db.now(), attempts=job["attempts"] + 1)
            t = threading.Thread(target=self._run_job, args=(job,), name=f"clipflow-job-{job['id']}", daemon=True)
            self._threads.append(t)
            t.start()

    def _project_logger(self, pid: str) -> logging.Logger:
        lg = logging.getLogger(f"clipflow.project.{pid}")
        lg.setLevel(logging.INFO)
        if not any(isinstance(h, logging.FileHandler) for h in lg.handlers):
            fh = logging.FileHandler(storage.log_path(pid), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            lg.addHandler(fh)
        return lg

    def _run_job(self, job: dict) -> None:
        job_id, pid, kind = job["id"], job["project_id"], job["kind"]
        lg = self._project_logger(pid)
        last_update = [0.0]

        def on_progress(stage: str, frac: float) -> None:
            now = time.monotonic()
            if now - last_update[0] < 0.4 and frac < 1.0:
                return
            last_update[0] = now
            db.update("jobs", job_id, stage=stage, progress=round(frac, 4))
            db.update("projects", pid, stage=stage, progress=round(frac, 4))

        def is_cancelled() -> bool:
            row = db.fetch_one("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))
            return bool(row and row["cancel_requested"]) or self._stop.is_set()

        ctx = JobContext(pid, on_progress=on_progress, is_cancelled=is_cancelled, logger=lg)
        with self._lock:
            self._running[job_id] = ctx
        started = time.monotonic()
        lg.info("Tarefa %s (%s) iniciada — tentativa %d/%d", job_id, kind, job["attempts"] + 1, job["max_attempts"])
        try:
            if kind == "analyze":
                nxt = runner.run_analysis(pid, ctx)
                self._finish(job_id, "done")
                if nxt == "render":
                    self._chain_render(pid)
                else:
                    db.update("projects", pid, status="awaiting_review", stage="Aguardando sua revisão", progress=1)
            elif kind == "render":
                payload = job["payload"] or {}
                res = runner.run_render(pid, payload.get("clip_ids"), ctx)
                self._finish(job_id, "done")
                msg = f"{res['done']} Shorts prontos" + (f", {res['failed']} com falha" if res["failed"] else "")
                db.update("projects", pid, status="completed", stage=msg, progress=1, error=None)
            elif kind == "concat":
                payload = job["payload"] or {}
                runner.run_concat_export(pid, payload.get("clip_id", ""), ctx)
                self._finish(job_id, "done")
                has_done = db.fetch_one("SELECT COUNT(*) AS n FROM clips WHERE project_id = ? AND status = 'done'",
                                        (pid,))["n"]
                db.update("projects", pid, status="completed" if has_done else "awaiting_review",
                          stage="Projeto do Concat pronto", progress=1, error=None)
            else:
                raise PipelineError(f"Tipo de tarefa desconhecido: {kind}")
            lg.info("Tarefa %s concluída em %.1fs", job_id, time.monotonic() - started)
        except Cancelled:
            if self._stop.is_set() and not db.fetch_one(
                    "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))["cancel_requested"]:
                # servidor desligando: volta para a fila para retomar depois
                db.update("jobs", job_id, status="queued", attempts=job["attempts"], stage="Interrompido")
            else:
                lg.info("Tarefa %s cancelada", job_id)
                self._finish(job_id, "cancelled", stage="Cancelado")
                db.update("projects", pid, status="cancelled", stage="Cancelado pelo usuário")
                runner.cleanup_work_dir(pid)
        except Exception as exc:  # noqa: BLE001
            retryable = isinstance(exc, PipelineError) and exc.retryable or not isinstance(exc, PipelineError)
            msg = str(exc) if isinstance(exc, PipelineError) else f"Erro inesperado: {exc}"
            lg.error("Tarefa %s falhou: %s\n%s", job_id, msg, traceback.format_exc())
            attempts = job["attempts"] + 1
            if retryable and attempts < job["max_attempts"]:
                delay = 5 * attempts
                db.update("jobs", job_id, status="queued", error=msg[:2000], run_after=time.time() + delay,
                          stage=f"Erro; nova tentativa em {delay}s")
                db.update("projects", pid, status="queued", stage=f"Nova tentativa em {delay}s: {msg[:150]}")
            else:
                self._finish(job_id, "failed", error=msg[:2000], stage="Falhou")
                db.update("projects", pid, status="failed", stage="Falhou", error=msg[:2000])
            runner.cleanup_work_dir(pid)
        finally:
            elapsed = time.monotonic() - started
            with db.conn() as c:
                c.execute("UPDATE projects SET processing_seconds = processing_seconds + ? WHERE id = ?",
                          (elapsed, pid))
            with self._lock:
                self._running.pop(job_id, None)
            self.wake()

    def _finish(self, job_id: int, status: str, error: str | None = None, stage: str = "Concluído") -> None:
        fields = {"status": status, "finished_at": db.now(), "error": error, "stage": stage}
        if status == "done":
            fields["progress"] = 1
        db.update("jobs", job_id, **fields)

    def _chain_render(self, pid: str) -> None:
        import json

        db.execute(
            "INSERT INTO jobs (project_id, kind, payload_json, status, max_attempts, created_at) "
            "VALUES (?, 'render', ?, 'queued', ?, ?)",
            (pid, json.dumps({}), int(config.get("limits.max_attempts")), db.now()),
        )
        db.update("projects", pid, status="queued", stage="Na fila para renderização")


worker = Worker()
