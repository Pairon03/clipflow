"""Cortes: revisão, ajustes, correção de legenda, arquivos e biblioteca."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import db, storage
from ..pipeline import editing, render, runner, transcribe
from ..security import safe_filename
from .common import LAYOUTS, MAX_CLIP_SECONDS, clip_public, get_clip_or_404, get_project_or_404, public_path
from .projects import ACTIVE_STATUSES, zip_clips

router = APIRouter(prefix="/api", tags=["clips"])


def _clip_words(clip: dict) -> list[dict]:
    if clip.get("words"):
        return clip["words"]
    tpath = runner.transcript_path(clip["project_id"])
    if not tpath.exists():
        return []
    return render.words_for_clip(transcribe.all_words(transcribe.load(tpath)), clip["start"], clip["end"])


class ClipPatch(BaseModel):
    selected: bool | None = None
    start: float | None = None
    end: float | None = None
    layout: str | None = None
    manual_x: float | None = Field(default=None, ge=0, le=1)
    text: str | None = Field(default=None, max_length=5000)
    titles: list[str] | None = None
    description: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] | None = None
    hook_choice: int | str | None = None   # índice do candidato, "none" (sem gancho) ou "auto"


@router.patch("/clips/{cid}")
def patch_clip(cid: str, body: ClipPatch):
    clip = get_clip_or_404(cid)
    project = get_project_or_404(clip["project_id"])
    if project["status"] in ACTIVE_STATUSES and (body.start is not None or body.end is not None or body.text):
        raise HTTPException(409, "Aguarde o processamento atual terminar para editar o corte")
    fields: dict = {}
    if body.selected is not None:
        fields["selected"] = 1 if body.selected else 0
        if clip["status"] in {"selected", "candidate"}:
            fields["status"] = "selected" if body.selected else "candidate"
    if body.start is not None or body.end is not None:
        start = clip["start"] if body.start is None else round(body.start, 3)
        end = clip["end"] if body.end is None else round(body.end, 3)
        dur_src = project.get("source_duration") or 0
        if start < 0 or (dur_src and end > dur_src + 0.5) or not 3 <= end - start <= MAX_CLIP_SECONDS:
            raise HTTPException(422, f"Intervalo inválido (3 a {MAX_CLIP_SECONDS}s dentro do vídeo)")
        fields.update(start=start, end=end, words_json=None)
        tpath = runner.transcript_path(clip["project_id"])
        if tpath.exists():
            words = render.words_for_clip(transcribe.all_words(transcribe.load(tpath)), start, end)
            fields["text"] = " ".join(w["text"] for w in words)
    if body.layout is not None:
        if body.layout not in LAYOUTS:
            raise HTTPException(422, "Enquadramento inválido")
        fields["layout"] = body.layout
    if body.manual_x is not None:
        fields["manual_x"] = body.manual_x
    if body.text is not None:
        base = _clip_words(clip | {"start": fields.get("start", clip["start"]), "end": fields.get("end", clip["end"]),
                                   "words": None if "words_json" in fields else clip.get("words")})
        try:
            new_words = editing.realign(base, body.text)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        fields["words_json"] = json.dumps(new_words, ensure_ascii=False)
        fields["text"] = " ".join(w["text"] for w in new_words)
    if body.titles is not None:
        fields["titles_json"] = [t.strip()[:100] for t in body.titles if t.strip()][:3]
    if body.description is not None:
        fields["description"] = body.description
    if body.hashtags is not None:
        fields["hashtags_json"] = [h.strip()[:40] for h in body.hashtags if h.strip()][:15]
    if "start" in fields:
        fields["hook_json"] = None                  # corte mudou: o gancho é avaliado de novo no render
    elif body.hook_choice is not None:
        hook = clip.get("hook")
        if not hook:
            raise HTTPException(409, "Este corte ainda não tem ganchos avaliados")
        choice = body.hook_choice
        if choice == "auto":
            choice = None
        elif isinstance(choice, int):
            if not 0 <= choice < len(hook.get("candidates") or []):
                raise HTTPException(422, "Gancho inválido")
        elif choice != "none":
            raise HTTPException(422, "Gancho inválido")
        fields["hook_json"] = hook | {"choice": choice}
    edits_video = {"start", "end", "layout", "manual_x", "words_json", "hook_json"} & fields.keys()
    if edits_video and clip["status"] == "done":
        fields["render_info_json"] = (clip.get("render_info") or {}) | {"stale": True}
    if fields:
        db.update("clips", cid, **fields)
    return clip_public(get_clip_or_404(cid))


@router.get("/clips/{cid}/words")
def clip_words(cid: str):
    clip = get_clip_or_404(cid)
    return {"words": _clip_words(clip), "edited": clip.get("words") is not None}


@router.post("/clips/{cid}/reset-text")
def reset_clip_text(cid: str):
    clip = get_clip_or_404(cid)
    db.update("clips", cid, words_json=None)
    words = _clip_words(clip | {"words": None})
    db.update("clips", cid, text=" ".join(w["text"] for w in words))
    return clip_public(get_clip_or_404(cid))


class SwapIn(BaseModel):
    with_id: str


@router.post("/clips/{cid}/swap")
def swap_clip(cid: str, body: SwapIn):
    """Substitui um corte selecionado por uma alternativa."""
    a = get_clip_or_404(cid)
    b = get_clip_or_404(body.with_id)
    if a["project_id"] != b["project_id"]:
        raise HTTPException(422, "Os cortes são de projetos diferentes")
    db.update("clips", a["id"], selected=0, status="candidate" if a["status"] != "done" else "done")
    db.update("clips", b["id"], selected=1, status="selected" if b["status"] != "done" else "done")
    return {"ok": True}


def _clip_file(cid: str, attr: str, media: str, download: bool, ext: str):
    clip = get_clip_or_404(cid)
    f = public_path(clip.get(attr))
    if not f:
        raise HTTPException(404, "Arquivo não disponível")
    name = None
    if download:
        title = (clip.get("titles") or [cid])[0]
        name = f"{safe_filename(title, 60)}{ext}"
    return FileResponse(f, media_type=media, filename=name)


@router.get("/clips/{cid}/video")
def clip_video(cid: str, download: bool = False):
    return _clip_file(cid, "output_path", "video/mp4", download, ".mp4")


@router.get("/clips/{cid}/thumb")
def clip_thumb(cid: str):
    return _clip_file(cid, "thumb_path", "image/jpeg", False, ".jpg")


@router.get("/clips/{cid}/srt")
def clip_srt(cid: str):
    return _clip_file(cid, "srt_path", "application/x-subrip", True, ".srt")


@router.delete("/clips/{cid}")
def delete_clip(cid: str):
    clip = get_clip_or_404(cid)
    for attr in ("output_path", "thumb_path", "srt_path"):
        f = public_path(clip.get(attr))
        if f:
            storage.remove_quietly(f)
    ass = storage.area_dir("subtitles", clip["project_id"]) / f"{cid}.ass"
    storage.remove_quietly(ass)
    db.execute("DELETE FROM clips WHERE id = ?", (cid,))
    return {"ok": True}


@router.get("/library")
def library(project_id: str | None = None, q: str | None = Query(default=None, max_length=100)):
    sql = ("SELECT c.*, p.name AS project_name, p.source_title AS project_source FROM clips c "
           "JOIN projects p ON p.id = c.project_id WHERE c.status = 'done'")
    params: list = []
    if project_id:
        storage.check_id(project_id)
        sql += " AND c.project_id = ?"
        params.append(project_id)
    if q:
        sql += " AND (c.text LIKE ? OR c.titles_json LIKE ? OR p.name LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY c.rendered_at DESC"
    return [clip_public(c) | {"project_name": c["project_name"]} for c in db.fetch_all(sql, tuple(params))]


@router.get("/library/zip")
def library_zip(ids: str = Query(..., max_length=20000)):
    id_list = [i for i in ids.split(",") if i]
    if not id_list or len(id_list) > 500:
        raise HTTPException(422, "Lista de cortes inválida")
    for i in id_list:
        try:
            storage.check_id(i)
        except storage.UnsafePathError:
            raise HTTPException(422, "Lista de cortes inválida")
    clips = db.fetch_all(f"SELECT * FROM clips WHERE status = 'done' AND id IN ({','.join('?' * len(id_list))}) "
                         "ORDER BY project_id, start", tuple(id_list))
    return zip_clips(clips, "ClipFlow_Shorts")


# ------------------------------------------------------------------ Concat (editor externo opcional)
@router.post("/clips/{cid}/concat")
def clip_to_concat(cid: str):
    """Enfileira a criação de um projeto editável no Concat para este corte."""
    from ..pipeline import concat_bridge
    from ..worker import worker

    clip = get_clip_or_404(cid)
    project = get_project_or_404(clip["project_id"])
    if not concat_bridge.find_executable():
        raise HTTPException(422, "Concat não encontrado. Instale o Concat ou informe o caminho em Configurações.")
    if project["status"] in ACTIVE_STATUSES:
        raise HTTPException(409, "Aguarde o processamento atual terminar")
    if not runner.transcript_path(clip["project_id"]).exists():
        raise HTTPException(409, "O projeto ainda não foi analisado")
    try:
        worker.enqueue(clip["project_id"], "concat", {"clip_id": cid})
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True}


@router.post("/clips/{cid}/concat/open")
def open_clip_in_concat(cid: str):
    """Abre o projeto do Concat deste corte na janela do editor (no computador onde o ClipFlow roda)."""
    from ..pipeline import concat_bridge
    from ..pipeline.errors import PipelineError

    clip = get_clip_or_404(cid)
    path = (clip.get("render_info") or {}).get("concat_project")
    folder = public_path(path)
    if not folder or not folder.is_dir():
        raise HTTPException(404, "Projeto do Concat ainda não foi criado para este corte")
    try:
        concat_bridge.open_in_editor(folder)
    except PipelineError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True, "path": str(folder)}


@router.get("/concat/status")
def concat_status():
    from ..pipeline import concat_bridge

    return concat_bridge.status()
