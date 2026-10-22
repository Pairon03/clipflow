"""Fila de publicação no YouTube, separada da fila de processamento.

- Um envio por vez, em segundo plano; renders continuam rodando ao mesmo tempo.
- Agendamento pelo próprio YouTube (publishAt): o vídeo sobe na hora e é publicado no horário escolhido,
  mesmo com o computador desligado.
- Limite diário do Google atingido: o envio espera e tenta de novo depois da virada da cota
  (meia-noite no horário do Pacífico).
- Queda de internet: tenta de novo com espera crescente e continua o envio de onde parou.
- Reinício do app: envios interrompidos voltam para a fila.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, db, storage, youtube_api
from .youtube_api import YouTubeError

log = logging.getLogger("clipflow.publisher")

PRIVACIES = {"private", "unlisted", "public"}
CATEGORIES = {"17": "Esportes", "20": "Jogos", "22": "Pessoas e blogs", "23": "Comédia", "24": "Entretenimento",
              "25": "Notícias e política", "26": "Guias e estilo", "27": "Educação"}
ACTIVE = ("queued", "uploading", "waiting_quota")
MAX_ATTEMPTS = 6
MIN_SCHEDULE_S = 15 * 60          # o YouTube exige o horário de publicação no futuro
MAX_TITLE = 100
MAX_DESCRIPTION_BYTES = 5000
MAX_TAGS_CHARS = 500


# ------------------------------------------------------------------ textos
def _clean(text: str) -> str:
    return re.sub(r"[<>]", "", text or "").strip()     # o YouTube recusa < e > em título e descrição


def clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", _clean(title))
    return t[:MAX_TITLE].rstrip()


def clean_description(text: str) -> str:
    d = _clean(text)
    raw = d.encode("utf-8")
    if len(raw) <= MAX_DESCRIPTION_BYTES:
        return d
    return raw[:MAX_DESCRIPTION_BYTES].decode("utf-8", "ignore").rstrip()


def build_tags(hashtags: list[str] | None, keywords: list[str] | None) -> list[str]:
    """Tags do YouTube: hashtags sem # + palavras-chave, sem repetir, dentro do limite de 500 caracteres."""
    out, seen, total = [], set(), 0
    for raw in [*(hashtags or []), *(keywords or [])]:
        t = _clean(str(raw)).lstrip("#").replace(",", " ").strip()
        t = re.sub(r"\s+", " ", t)[:30]
        if len(t) < 2 or t.lower() in seen:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)   # tags com espaço contam as aspas
        if total + cost > MAX_TAGS_CHARS:
            break
        seen.add(t.lower())
        out.append(t)
        total += cost
    return out


def tiktok_caption(clip: dict, title: str | None = None) -> str:
    """Legenda pronta para colar no TikTok: título + descrição (que já termina com as hashtags)."""
    title = (title or (clip.get("titles") or [""])[0]).strip()
    desc = (clip.get("description") or "").strip()
    if not desc:
        desc = " ".join(clip.get("hashtags") or [])
    return f"{title}\n\n{desc}".strip() if title else desc


def _rfc3339(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def video_metadata(pub: dict, now: float | None = None) -> tuple[dict, str | None]:
    """Corpo do videos.insert. Devolve (metadados, aviso). Se o horário agendado já passou, publica na hora."""
    now = time.time() if now is None else now
    status = {"privacyStatus": pub["privacy"], "selfDeclaredMadeForKids": False, "embeddable": True}
    note = None
    if pub.get("publish_at"):
        if pub["publish_at"] - now < 5 * 60:
            status["privacyStatus"] = "public"
            note = "O horário agendado já tinha passado quando o envio aconteceu; publicado na hora."
        else:
            status["privacyStatus"] = "private"
            status["publishAt"] = _rfc3339(pub["publish_at"])
    lang = str(config.get("transcription.language") or "pt")
    snippet = {"title": pub["title"], "description": pub["description"], "tags": pub.get("tags") or [],
               "categoryId": pub["category_id"], "defaultLanguage": lang, "defaultAudioLanguage": lang}
    return {"snippet": snippet, "status": status}, note


def next_quota_reset(now: float | None = None) -> float:
    """A cota do YouTube vira à meia-noite do Pacífico (07:00 ou 08:00 UTC). 08:05 UTC cobre os dois casos."""
    now_dt = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    target = now_dt.replace(hour=8, minute=5, second=0, microsecond=0)
    if target <= now_dt:
        target += timedelta(days=1)
    return target.timestamp()


# ------------------------------------------------------------------ fila
def create(clip: dict, *, title: str, privacy: str, publish_at: float | None, category_id: str,
           notify: bool) -> dict:
    pid = db.new_id()
    description = clean_description(clip.get("description") or "")
    tags = build_tags(clip.get("hashtags"), clip.get("keywords"))
    db.execute(
        "INSERT INTO publications (id, clip_id, platform, status, title, description, tags_json, privacy, "
        "publish_at, category_id, notify, created_at) VALUES (?, ?, 'youtube', 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, clip["id"], clean_title(title), description, json.dumps(tags, ensure_ascii=False),
         privacy, publish_at, category_id, 1 if notify else 0, db.now()))
    publisher.wake()
    return get(pid)


def get(pub_id: str) -> dict | None:
    return db.fetch_one("SELECT * FROM publications WHERE id = ?", (pub_id,))


def public(pub: dict) -> dict:
    out = {k: v for k, v in pub.items() if k != "session_url"}
    out["progress"] = round(pub["bytes_sent"] / pub["size_bytes"], 4) if pub.get("size_bytes") else 0
    return out


def cancel(pub_id: str) -> bool:
    pub = get(pub_id)
    if not pub or pub["status"] not in ACTIVE:
        return False
    if pub["status"] == "uploading":
        db.update("publications", pub_id, cancel_requested=1)
    else:
        db.update("publications", pub_id, status="cancelled", finished_at=db.now())
    return True


def retry(pub_id: str) -> bool:
    pub = get(pub_id)
    if not pub or pub["status"] not in ("failed", "cancelled"):
        return False
    db.update("publications", pub_id, status="queued", error=None, attempts=0, run_after=0, cancel_requested=0,
              finished_at=None)
    publisher.wake()
    return True


class Publisher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        db.execute("UPDATE publications SET status = 'queued' WHERE status = 'uploading'")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipflow-publisher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                while not self._stop.is_set() and self.run_next():
                    pass
            except Exception:  # nunca deixa a fila morrer
                log.exception("Erro na fila de publicação")
            self._wake.wait(10.0)
            self._wake.clear()

    def run_next(self) -> bool:
        """Envia o próximo da fila (se houver e se a conta estiver conectada). Devolve True se tentou um."""
        if not youtube_api.status()["connected"]:
            return False
        pub = db.fetch_one("SELECT * FROM publications WHERE status IN ('queued','waiting_quota') AND run_after <= ? "
                           "ORDER BY COALESCE(publish_at, created_at), created_at LIMIT 1", (time.time(),))
        if not pub:
            return False
        with db.conn() as c:   # reserva atômica: dois despachantes nunca enviam o mesmo vídeo
            claimed = c.execute("UPDATE publications SET status = 'uploading' WHERE id = ? "
                                "AND status IN ('queued','waiting_quota')", (pub["id"],)).rowcount
        if claimed:
            self._upload(pub)
        return True

    def _upload(self, pub: dict) -> None:
        pid = pub["id"]
        clip = db.fetch_one("SELECT * FROM clips WHERE id = ?", (pub["clip_id"],))
        path = _clip_file(clip)
        if not path:
            db.update("publications", pid, status="failed", finished_at=db.now(),
                      error="O arquivo do Short não existe mais. Renderize o corte de novo.")
            return
        size = path.stat().st_size
        db.update("publications", pid, status="uploading", started_at=pub["started_at"] or db.now(),
                  attempts=pub["attempts"] + 1, size_bytes=size, error=None)
        last = [0.0]

        def progress(sent: int, total: int) -> None:
            if time.monotonic() - last[0] > 0.5 or sent >= total:
                last[0] = time.monotonic()
                db.update("publications", pid, bytes_sent=sent)

        def cancelled() -> bool:
            row = db.fetch_one("SELECT cancel_requested FROM publications WHERE id = ?", (pid,))
            return bool(row and row["cancel_requested"]) or self._stop.is_set()

        try:
            meta, note = video_metadata(pub)
            session, offset, video = pub.get("session_url"), 0, None
            if session and pub.get("size_bytes") == size:
                try:
                    offset, video = youtube_api.query_offset(session, size)
                except YouTubeError as exc:
                    if exc.kind != "restart":
                        raise
                    session = None
            else:
                session = None
            if not session:
                session = youtube_api.start_upload(meta, size, notify=bool(pub["notify"]))
                db.update("publications", pid, session_url=session, bytes_sent=0, note=note)
                offset = 0
            if video is None:
                video = youtube_api.upload_file(session, path, offset, on_progress=progress, is_cancelled=cancelled)
            vid = str(video.get("id") or "")
            if not vid:
                raise YouTubeError("O YouTube terminou o envio sem devolver o vídeo", "retry")
            final = "scheduled" if meta["status"].get("publishAt") else "done"
            db.update("publications", pid, status=final, video_id=vid, url=f"https://youtube.com/shorts/{vid}",
                      bytes_sent=size, session_url=None, finished_at=db.now(), error=None, note=note)
            log.info("Publicação %s enviada: vídeo %s", pid, vid)
        except YouTubeError as exc:
            self._handle_error(pub, exc)
        except Exception as exc:
            log.exception("Falha inesperada no envio %s", pid)
            self._handle_error(pub, YouTubeError(f"Erro inesperado: {exc}", "retry"))

    def _handle_error(self, pub: dict, exc: YouTubeError) -> None:
        pid = pub["id"]
        attempts = pub["attempts"] + 1
        if exc.kind == "cancelled":
            if self._stop.is_set() and not get(pid)["cancel_requested"]:
                db.update("publications", pid, status="queued", attempts=pub["attempts"])   # app fechando
            else:
                db.update("publications", pid, status="cancelled", finished_at=db.now(), cancel_requested=0)
        elif exc.kind == "auth":
            # sem autorização nada sobe: o envio volta para a fila e espera a conta ser conectada de novo
            youtube_api.mark_invalid(str(exc))
            db.update("publications", pid, status="queued", attempts=pub["attempts"], error=str(exc))
        elif exc.kind == "quota":
            db.update("publications", pid, status="waiting_quota", attempts=pub["attempts"],
                      run_after=next_quota_reset(), error=str(exc))
        elif exc.kind == "restart":
            db.update("publications", pid, status="queued", session_url=None, bytes_sent=0, error=str(exc))
        elif exc.kind == "retry" and attempts < MAX_ATTEMPTS:
            delay = min(30 * 2 ** (attempts - 1), 30 * 60)
            db.update("publications", pid, status="queued", run_after=time.time() + delay,
                      error=f"{exc} — nova tentativa em {delay // 60 or 1} min")
        else:
            db.update("publications", pid, status="failed", finished_at=db.now(), error=str(exc))
        log.warning("Publicação %s: %s (%s)", pid, exc, exc.kind)


def _clip_file(clip: dict | None) -> Path | None:
    if not clip or clip.get("status") != "done" or not clip.get("output_path"):
        return None
    try:
        p = storage.ensure_inside_root(clip["output_path"])
    except storage.UnsafePathError:
        return None
    return p if p.is_file() else None


publisher = Publisher()
