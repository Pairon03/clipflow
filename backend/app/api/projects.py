"""Projetos: criação, acompanhamento, revisão, renderização e exclusão."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .. import db, storage
from ..pipeline import runner, transcribe, youtube
from ..pipeline.errors import FatalPipelineError
from ..security import ValidationError, check_rights, parse_youtube_url, safe_filename
from ..worker import worker
from . import uploads
from .common import (clip_public, get_project_or_404, project_public, public_path, validate_options)

router = APIRouter(prefix="/api/projects", tags=["projects"])

ACTIVE_STATUSES = ("queued", "downloading", "transcribing", "analyzing", "rendering")


class SourceIn(BaseModel):
    type: str
    url: str | None = None
    upload_id: str | None = None


class RightsIn(BaseModel):
    confirmed: bool = False
    basis: str = ""
    note: str = ""


class ProjectIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    source: SourceIn
    subtitle_upload_id: str | None = None
    rights: RightsIn
    options: dict = {}
    force: bool = False


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with path.open("rb") as fh:
        h.update(fh.read(4 * 1024 * 1024))
        if size > 8 * 1024 * 1024:
            fh.seek(-4 * 1024 * 1024, 2)
            h.update(fh.read())
    return "file:" + h.hexdigest()[:32]


def _duplicate(source_key: str) -> dict | None:
    return db.fetch_one(
        "SELECT id, name, status FROM projects WHERE source_key = ? AND status != 'cancelled' "
        "AND status != 'failed' ORDER BY created_at DESC LIMIT 1", (source_key,))


@router.post("")
def create_project(body: ProjectIn):
    try:
        basis, note = check_rights(body.rights.confirmed, body.rights.basis, body.rights.note)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    options = validate_options(body.options)
    pid = db.new_id()
    now = db.now()
    fields: dict = {}

    if body.source.type == "youtube":
        try:
            vid = parse_youtube_url(body.source.url or "")
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        source_key = f"youtube:{vid}"
        dup = _duplicate(source_key)
        if dup and not body.force:
            raise HTTPException(409, {"message": "Este vídeo já foi processado ou está em processamento.",
                                      "project_id": dup["id"], "name": dup["name"]})
        try:
            meta = youtube.fetch_metadata(vid)
        except FatalPipelineError as exc:
            raise HTTPException(422, str(exc))
        fields = {"source_type": "youtube", "source_url": meta["url"], "source_key": source_key,
                  "source_title": meta["title"], "source_channel": meta["channel"],
                  "source_duration": meta["duration"], "source_thumbnail": meta["thumbnail"]}
        name = body.name or meta["title"]
        upload_meta = None
    elif body.source.type == "upload":
        upload_meta = uploads.read_meta(body.source.upload_id or "")
        if upload_meta.get("kind") != "video":
            raise HTTPException(422, "Upload não é um vídeo")
        up_file = uploads.upload_dir(upload_meta["token"]) / f"source{upload_meta['ext']}"
        source_key = _file_fingerprint(up_file)
        dup = _duplicate(source_key)
        if dup and not body.force:
            raise HTTPException(409, {"message": "Este arquivo já foi processado ou está em processamento.",
                                      "project_id": dup["id"], "name": dup["name"]})
        info = upload_meta["info"]
        fields = {"source_type": "upload", "source_key": source_key, "source_title": upload_meta["filename"],
                  "source_duration": info["duration"], "source_width": info["width"],
                  "source_height": info["height"], "source_size": upload_meta["size"]}
        name = body.name or upload_meta["filename"]
    else:
        raise HTTPException(422, "Tipo de origem inválido")

    sub_meta = None
    if body.subtitle_upload_id:
        sub_meta = uploads.read_meta(body.subtitle_upload_id)
        if sub_meta.get("kind") != "subtitle":
            raise HTTPException(422, "Upload de legenda inválido")

    db.execute(
        "INSERT INTO projects (id, name, status, stage, source_type, rights_basis, rights_note, "
        "rights_confirmed_at, options_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (pid, name.strip()[:120], "queued", "Na fila", fields["source_type"], basis, note, now,
         json.dumps(options), now, now),
    )
    db.update("projects", pid, **fields)

    if upload_meta:
        up_dir = uploads.upload_dir(upload_meta["token"])
        dst = runner.copy_upload(up_dir / f"source{upload_meta['ext']}", pid, upload_meta["ext"])
        thumb = up_dir / "thumb.jpg"
        if thumb.exists():
            shutil.move(str(thumb), storage.area_dir("projects", pid) / "thumb.jpg")
        storage.remove_quietly(up_dir)
        db.update("projects", pid, source_path=str(dst))
    if sub_meta:
        sd = uploads.upload_dir(sub_meta["token"])
        shutil.move(str(sd / f"subtitles{sub_meta['ext']}"),
                    storage.area_dir("downloads", pid) / f"subtitles{sub_meta['ext']}")
        storage.remove_quietly(sd)

    project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (pid,))
    # registro de origem e autorização (fica junto dos arquivos do projeto)
    storage.write_project_json(pid, {
        "id": pid, "name": project["name"], "created_at": now,
        "source": {k: project[k] for k in ("source_type", "source_url", "source_key", "source_title",
                                           "source_channel", "source_duration")},
        "rights": {"basis": basis, "note": note, "confirmed_at": now},
        "subtitle_import": bool(sub_meta), "options": options,
    })
    worker.enqueue(pid, "analyze")
    return project_public(db.fetch_one("SELECT * FROM projects WHERE id = ?", (pid,)))


@router.get("")
def list_projects(limit: int = 100):
    rows = db.fetch_all(
        "SELECT p.*, (SELECT COUNT(*) FROM clips c WHERE c.project_id = p.id AND c.status = 'done') AS clips_done, "
        "(SELECT COUNT(*) FROM clips c WHERE c.project_id = p.id AND c.selected = 1) AS clips_selected "
        "FROM projects p ORDER BY p.created_at DESC LIMIT ?", (min(max(limit, 1), 500),))
    return [project_public(r) for r in rows]


@router.get("/{pid}")
def get_project(pid: str):
    p = get_project_or_404(pid)
    clips = db.fetch_all("SELECT * FROM clips WHERE project_id = ? ORDER BY selected DESC, "
                         "CASE WHEN selected = 1 THEN start ELSE -score END", (pid,))
    job = db.fetch_one("SELECT id, kind, status, stage, progress, attempts, max_attempts, error, created_at, "
                       "started_at, finished_at FROM jobs WHERE project_id = ? ORDER BY id DESC LIMIT 1", (pid,))
    out = project_public(p)
    from .clips import latest_publications

    pubs = latest_publications([c["id"] for c in clips if c["status"] == "done"])
    out["clips"] = [clip_public(c) | {"publication": pubs.get(c["id"])} for c in clips]
    out["job"] = job
    out["has_transcript"] = runner.transcript_path(pid).exists()
    return out


@router.post("/{pid}/cancel")
def cancel_project(pid: str):
    get_project_or_404(pid)
    if not worker.cancel_project(pid):
        raise HTTPException(409, "Não há tarefa em andamento para cancelar")
    return {"ok": True}


@router.post("/{pid}/retry")
def retry_project(pid: str):
    p = get_project_or_404(pid)
    if p["status"] in ACTIVE_STATUSES:
        raise HTTPException(409, "O projeto já está em processamento")
    has_selected = db.fetch_one("SELECT COUNT(*) AS n FROM clips WHERE project_id = ? AND selected = 1", (pid,))["n"]
    kind = "render" if runner.transcript_path(pid).exists() and has_selected else "analyze"
    try:
        worker.enqueue(pid, kind)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "kind": kind}


class ReselectIn(BaseModel):
    count: int | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    style: str | None = None


@router.post("/{pid}/reselect")
def reselect(pid: str, body: ReselectIn):
    """Refaz a seleção de cortes com outra quantidade/duração (reaproveita a transcrição)."""
    p = get_project_or_404(pid)
    if p["status"] in ACTIVE_STATUSES:
        raise HTTPException(409, "Aguarde o processamento atual terminar")
    tpath = runner.transcript_path(pid)
    if not tpath.exists():
        raise HTTPException(409, "O projeto ainda não tem transcrição")
    opts = dict(p["options"] or {})
    for k in ("count", "min_duration", "max_duration", "style"):
        v = getattr(body, k)
        if v is not None:
            opts[k] = v
    opts = validate_options(opts | {"caption_colors": opts.get("caption_colors")})
    try:
        runner.select_clips(pid, transcribe.load(tpath), opts)
    except FatalPipelineError as exc:
        raise HTTPException(422, str(exc))
    db.update("projects", pid, options_json=opts, status="awaiting_review", stage="Aguardando sua revisão")
    return get_project(pid)


class OptionsIn(BaseModel):
    options: dict


@router.patch("/{pid}/options")
def update_options(pid: str, body: OptionsIn):
    """Altera opções de renderização (legenda, enquadramento...) antes de renderizar de novo."""
    p = get_project_or_404(pid)
    merged = dict(p["options"] or {}) | body.options
    opts = validate_options(merged)
    db.update("projects", pid, options_json=opts)
    return {"options": opts}


class RenderIn(BaseModel):
    clip_ids: list[str] | None = None


@router.post("/{pid}/render")
def render_project(pid: str, body: RenderIn):
    p = get_project_or_404(pid)
    if p["status"] in ACTIVE_STATUSES:
        raise HTTPException(409, "O projeto já está em processamento")
    if not runner.transcript_path(pid).exists():
        raise HTTPException(409, "O projeto ainda não foi analisado")
    ids = body.clip_ids
    if ids:
        for cid in ids:
            storage.check_id(cid)
        n = db.fetch_one(f"SELECT COUNT(*) AS n FROM clips WHERE project_id = ? AND id IN ({','.join('?' * len(ids))})",
                         (pid, *ids))["n"]
        if n != len(ids):
            raise HTTPException(422, "Corte inválido na lista")
    else:
        n = db.fetch_one("SELECT COUNT(*) AS n FROM clips WHERE project_id = ? AND selected = 1", (pid,))["n"]
        if n == 0:
            raise HTTPException(422, "Selecione pelo menos um corte")
    try:
        worker.enqueue(pid, "render", {"clip_ids": ids} if ids else {})
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@router.delete("/{pid}")
def delete_project(pid: str):
    get_project_or_404(pid)
    worker.cancel_project(pid)
    import time

    for _ in range(50):  # espera a tarefa em execução encerrar antes de apagar os arquivos
        if not db.fetch_one("SELECT id FROM jobs WHERE project_id = ? AND status = 'running'", (pid,)):
            break
        time.sleep(0.2)
    storage.remove_project_files(pid)
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    return {"ok": True}


@router.get("/{pid}/source")
def project_source(pid: str):
    p = get_project_or_404(pid)
    f = public_path(p.get("source_path"))
    if not f:
        raise HTTPException(404, "Vídeo de origem indisponível")
    return FileResponse(f)


@router.get("/{pid}/thumb")
def project_thumb(pid: str):
    get_project_or_404(pid)
    f = storage.area_dir("projects", pid) / "thumb.jpg"
    if f.exists():
        return FileResponse(f, media_type="image/jpeg")
    first = db.fetch_one("SELECT thumb_path FROM clips WHERE project_id = ? AND thumb_path IS NOT NULL LIMIT 1", (pid,))
    tf = public_path(first["thumb_path"]) if first else None
    if tf:
        return FileResponse(tf, media_type="image/jpeg")
    raise HTTPException(404, "Sem miniatura")


@router.get("/{pid}/transcript")
def project_transcript(pid: str):
    get_project_or_404(pid)
    tpath = runner.transcript_path(pid)
    if not tpath.exists():
        raise HTTPException(404, "Transcrição ainda não disponível")
    t = transcribe.load(tpath)
    return {"engine": t["engine"], "language": t["language"],
            "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in t["segments"]]}


@router.get("/{pid}/transcript.srt")
def project_transcript_srt(pid: str):
    p = get_project_or_404(pid)
    f = storage.area_dir("transcripts", pid) / "transcript.srt"
    if not f.exists():
        raise HTTPException(404, "Transcrição ainda não disponível")
    return FileResponse(f, media_type="application/x-subrip", filename=f"{safe_filename(p['name'])}.srt")


@router.get("/{pid}/log", response_class=PlainTextResponse)
def project_log(pid: str, lines: int = 200):
    get_project_or_404(pid)
    f = storage.log_path(pid)
    if not f.exists():
        return ""
    content = f.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-min(max(lines, 1), 2000):])


def zip_clips(clips: list[dict], name: str) -> FileResponse:
    files = [(c, public_path(c.get("output_path"))) for c in clips]
    files = [(c, f) for c, f in files if f]
    if not files:
        raise HTTPException(404, "Nenhum vídeo pronto para baixar")
    tmp = storage.root() / "tmp" / f"{db.new_id()}.zip"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        manifest = []
        for i, (c, f) in enumerate(files, 1):
            base = f"{i:02d}_{safe_filename((c.get('titles') or [c['id']])[0], 50)}"
            zf.write(f, f"{base}.mp4")
            srt = public_path(c.get("srt_path"))
            if srt:
                zf.write(srt, f"{base}.srt")
            manifest.append(f"{base}.mp4\nTítulos sugeridos: {' | '.join(c.get('titles') or [])}\n"
                            f"Descrição:\n{c.get('description', '')}\n")
        zf.writestr("LEIA-ME_titulos_e_descricoes.txt", "\n-----\n".join(manifest))
    return FileResponse(tmp, media_type="application/zip", filename=f"{safe_filename(name)}.zip",
                        background=BackgroundTask(storage.remove_quietly, tmp))


@router.get("/{pid}/zip")
def project_zip(pid: str):
    p = get_project_or_404(pid)
    clips = db.fetch_all("SELECT * FROM clips WHERE project_id = ? AND status = 'done' ORDER BY start", (pid,))
    return zip_clips(clips, p["name"])
