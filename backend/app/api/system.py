"""Painel, configurações, verificação do sistema e consulta de vídeos do YouTube."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, db, storage
from ..pipeline import concat_bridge, ffmpeg, framing, llm, transcribe, youtube
from ..pipeline.errors import FatalPipelineError
from ..security import RIGHTS_BASES, ValidationError, parse_youtube_url
from ..worker import worker
from .common import CAPTION_STYLES, LAYOUTS, MAX_CLIP_SECONDS, STYLES

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/meta")
def meta():
    return {
        "styles": {k: v["label"] for k, v in STYLES.items()},
        "style_defaults": {k: {"caption_style": v["caption_style"], "layout": v["layout"]} for k, v in STYLES.items()},
        "caption_styles": sorted(CAPTION_STYLES),
        "layouts": sorted(LAYOUTS),
        "rights_bases": RIGHTS_BASES,
        "max_clip_seconds": MAX_CLIP_SECONDS,
        "max_clips": config.get("limits.max_clips_per_project"),
        "max_upload_mb": config.get("limits.max_upload_mb"),
        "max_source_minutes": config.get("limits.max_source_minutes"),
        "concat_available": bool(concat_bridge.find_executable()),
        "ffmpeg_available": bool(ffmpeg._find("ffmpeg") and ffmpeg._find("ffprobe")),
    }


@router.get("/dashboard")
def dashboard():
    p = db.fetch_one(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
        "SUM(CASE WHEN status IN ('queued','downloading','transcribing','analyzing','rendering') THEN 1 ELSE 0 END) AS active, "
        "SUM(CASE WHEN status = 'awaiting_review' THEN 1 ELSE 0 END) AS review, "
        "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
        "COALESCE(SUM(processing_seconds), 0) AS processing_seconds, "
        "COALESCE(SUM(CASE WHEN status != 'failed' THEN source_duration ELSE 0 END), 0) AS source_seconds "
        "FROM projects")
    c = db.fetch_one("SELECT COUNT(*) AS shorts, COALESCE(SUM(duration), 0) AS shorts_seconds, "
                     "COALESCE(SUM(size_bytes), 0) AS shorts_bytes FROM clips WHERE status = 'done'")
    recent = db.fetch_all(
        "SELECT p.id, p.name, p.status, p.stage, p.progress, p.source_type, p.source_duration, p.created_at, "
        "p.source_thumbnail, (SELECT COUNT(*) FROM clips c WHERE c.project_id = p.id AND c.status = 'done') AS clips_done "
        "FROM projects p ORDER BY p.created_at DESC LIMIT 8")
    usage = storage.usage_by_area()
    disk = shutil.disk_usage(storage.root())
    videos = p["total"] or 0
    return {
        "videos_processed": videos,
        "projects_completed": p["completed"] or 0,
        "projects_active": p["active"] or 0,
        "projects_review": p["review"] or 0,
        "projects_failed": p["failed"] or 0,
        "shorts_total": c["shorts"],
        "shorts_seconds": c["shorts_seconds"],
        "processing_seconds": round(p["processing_seconds"], 1),
        "source_seconds": round(p["source_seconds"], 1),
        # quantos segundos de processamento por segundo de vídeo de origem
        "realtime_factor": round(p["processing_seconds"] / p["source_seconds"], 2) if p["source_seconds"] else None,
        "storage_bytes": sum(usage.values()),
        "storage_by_area": usage,
        "disk_free_bytes": disk.free,
        "queue": worker.stats(),
        "recent": recent,
    }


@router.get("/system/status")
def system_status():
    det = framing.get_detector()
    return {
        "ffmpeg": ffmpeg.available(),
        "whisper": transcribe.whisper_available(),
        "ollama": llm.status(),
        "face_detector": det.kind,
        "yt_dlp": _ytdlp_version(),
        "data_dir": str(storage.root()),
        "concat": {"path": str(concat_bridge.find_executable() or "") or None},
        "queue": worker.stats(),
    }


def _ytdlp_version() -> str | None:
    try:
        import yt_dlp

        return yt_dlp.version.__version__
    except Exception:
        return None


@router.get("/settings")
def get_settings():
    return {"values": config.all_settings(), "editable": sorted(config.EDITABLE),
            "allowed": {k: sorted(v) for k, v in config.ALLOWED_VALUES.items()}}


class SettingsIn(BaseModel):
    values: dict


@router.put("/settings")
def put_settings(body: SettingsIn):
    coerced = {}
    for key, value in body.values.items():
        try:
            coerced[key] = config.coerce(key, value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
    for key, value in coerced.items():
        db.save_setting(key, value)
    worker.wake()
    return get_settings()


class InspectIn(BaseModel):
    url: str


@router.post("/youtube/inspect")
def youtube_inspect(body: InspectIn):
    try:
        vid = parse_youtube_url(body.url)
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    try:
        meta = youtube.fetch_metadata(vid)
    except FatalPipelineError as exc:
        raise HTTPException(422, str(exc))
    dup = db.fetch_one("SELECT id, name, status FROM projects WHERE source_key = ? AND status NOT IN "
                       "('failed','cancelled') ORDER BY created_at DESC LIMIT 1", (f"youtube:{vid}",))
    return meta | {"duplicate": dup}


@router.post("/youtube/validate")
def youtube_validate(body: InspectIn):
    """Validação rápida e offline do formato do link (sem acessar o YouTube)."""
    try:
        vid = parse_youtube_url(body.url)
    except ValidationError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "video_id": vid}
