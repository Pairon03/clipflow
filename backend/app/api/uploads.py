"""Upload de vídeos e legendas (streaming direto para o disco, com limite de tamanho)."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request

from .. import config, storage
from ..pipeline import ffmpeg
from ..pipeline.errors import PipelineError
from ..security import ValidationError, check_subtitle_filename, check_video_filename, display_name

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
UPLOAD_TTL_S = 24 * 3600
MAX_SUB_BYTES = 5 * 1024 * 1024


def uploads_root() -> Path:
    d = storage.root() / "tmp" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_dir(token: str) -> Path:
    if not token or len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
        raise HTTPException(400, "Upload inválido")
    d = uploads_root() / token
    if not d.is_dir():
        raise HTTPException(404, "Upload não encontrado ou expirado. Envie o arquivo novamente.")
    return d


def read_meta(token: str) -> dict:
    return json.loads((upload_dir(token) / "meta.json").read_text(encoding="utf-8"))


def cleanup_expired() -> int:
    removed = 0
    now = time.time()
    for d in uploads_root().iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > UPLOAD_TTL_S:
                storage.remove_quietly(d)
                removed += 1
        except OSError:
            pass
    return removed


async def _receive(request: Request, dest: Path, max_bytes: int) -> int:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(413, f"Arquivo maior que o limite de {max_bytes // (1024 * 1024)} MB")
    size = 0
    with dest.open("wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                fh.close()
                storage.remove_quietly(dest.parent)
                raise HTTPException(413, f"Arquivo maior que o limite de {max_bytes // (1024 * 1024)} MB")
            fh.write(chunk)
    if size == 0:
        storage.remove_quietly(dest.parent)
        raise HTTPException(400, "Arquivo vazio")
    return size


@router.put("/video")
async def upload_video(request: Request):
    """Corpo da requisição = bytes do arquivo. Cabeçalho X-Filename = nome original (URL-encoded)."""
    filename = unquote(request.headers.get("x-filename", ""))
    try:
        ext = check_video_filename(filename)
    except ValidationError as exc:
        raise HTTPException(415, str(exc))
    token = uuid.uuid4().hex
    d = uploads_root() / token
    d.mkdir()
    dest = d / f"source{ext}"
    size = await _receive(request, dest, int(config.get("limits.max_upload_mb")) * 1024 * 1024)
    try:
        info = ffmpeg.probe(dest)
    except PipelineError as exc:
        storage.remove_quietly(d)
        raise HTTPException(422, str(exc))
    if not info.has_audio:
        storage.remove_quietly(d)
        raise HTTPException(422, "O vídeo não possui áudio — é necessário para transcrição")
    max_min = config.get("limits.max_source_minutes")
    if info.duration > max_min * 60:
        storage.remove_quietly(d)
        raise HTTPException(422, f"Vídeo com {info.duration / 60:.0f} min excede o limite de {max_min} min")
    if info.duration < 10:
        storage.remove_quietly(d)
        raise HTTPException(422, "Vídeo muito curto (mínimo 10 segundos)")
    meta = {"token": token, "kind": "video", "filename": display_name(filename), "ext": ext, "size": size,
            "info": info.as_dict(), "created_at": time.time()}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    try:
        ffmpeg.thumbnail(dest, d / "thumb.jpg", at=min(5.0, info.duration / 3), width=480)
    except PipelineError:
        pass
    return meta


@router.put("/subtitle")
async def upload_subtitle(request: Request):
    filename = unquote(request.headers.get("x-filename", ""))
    try:
        ext = check_subtitle_filename(filename)
    except ValidationError as exc:
        raise HTTPException(415, str(exc))
    token = uuid.uuid4().hex
    d = uploads_root() / token
    d.mkdir()
    dest = d / f"subtitles{ext}"
    size = await _receive(request, dest, MAX_SUB_BYTES)
    try:
        import pysubs2

        subs = pysubs2.load(str(dest), encoding="utf-8")
        n = len([e for e in subs if not e.is_comment])
    except Exception:
        storage.remove_quietly(d)
        raise HTTPException(422, "Legenda inválida (use .srt ou .vtt em UTF-8)")
    if n == 0:
        storage.remove_quietly(d)
        raise HTTPException(422, "A legenda está vazia")
    meta = {"token": token, "kind": "subtitle", "filename": display_name(filename), "ext": ext, "size": size,
            "cues": n, "created_at": time.time()}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


@router.get("/{token}/thumb")
def upload_thumb(token: str):
    from fastapi.responses import FileResponse

    f = upload_dir(token) / "thumb.jpg"
    if not f.exists():
        raise HTTPException(404, "Sem miniatura")
    return FileResponse(f, media_type="image/jpeg")


@router.delete("/{token}")
def delete_upload(token: str):
    storage.remove_quietly(upload_dir(token))
    return {"ok": True}
