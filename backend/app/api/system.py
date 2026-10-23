"""Painel, configurações, verificação do sistema e consulta de vídeos do YouTube."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
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


# ------------------------------------------------------------------ identidade do canal (cartão de título)
@router.get("/branding")
def get_branding():
    from ..pipeline import branding

    b = branding.current()
    return {"name": b["name"], "handle": b["handle"], "has_avatar": b["avatar"] is not None,
            "configured": b["configured"], "tweet_text": config.get("branding.tweet_text"),
            "tweet_mode": config.get("branding.tweet_mode")}


@router.put("/branding/avatar")
async def put_avatar(request: Request):
    from ..pipeline import branding

    data = await request.body()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Imagem vazia ou maior que 5 MB")
    try:
        branding.save_avatar(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True}


@router.get("/branding/avatar")
def get_avatar():
    from ..pipeline import branding

    p = branding.avatar_path()
    if not p.is_file():
        raise HTTPException(404, "Sem avatar")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/branding/avatar")
def delete_avatar():
    from ..pipeline import branding

    storage.remove_quietly(branding.avatar_path())
    return {"ok": True}


_PREVIEW_CARD = {"lead": "Craque Neto respondeu:", "guest": "Craque Neto", "quote": "O maior erro foi brigar com o treinador",
                 "question": "Qual foi o maior erro da sua carreira?",
                 "headline": "Craque Neto respondeu: “O maior erro foi brigar com o treinador”"}


@router.get("/branding/preview")
def title_preview(style: str = "tweet"):
    """Prévia (PNG) de um estilo de título sobre fundo escuro, com um texto de exemplo."""
    import io

    from PIL import Image

    from ..pipeline import overlay

    if style not in overlay.STYLES or style == "nenhum":
        raise HTTPException(422, "Estilo inválido")
    tmp = storage.root() / "tmp" / f"preview_{style}.png"
    if not overlay.render_card(style, _PREVIEW_CARD, tmp, 1080, 1920):
        raise HTTPException(422, "Sem texto para este estilo")
    card = Image.open(tmp)
    bg = Image.new("RGBA", card.size, (40, 40, 48, 255))
    bg.alpha_composite(card)
    crop = bg.crop((0, 0, 1080, 760)).convert("RGB").resize((540, 380))
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=85)
    storage.remove_quietly(tmp)
    from fastapi.responses import Response

    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ filtros de cor
@router.get("/filters")
def list_filters():
    from ..pipeline import color

    return [{"key": k, "name": name} for k, (name, _) in color.FILTERS.items()]


@router.get("/filters/preview")
def filter_preview(name: str = "nenhum", project_id: str | None = None):
    """Quadro do vídeo do projeto (ou do projeto mais recente) com o filtro aplicado."""
    from ..pipeline import color
    from .common import get_project_or_404

    if name not in color.FILTERS:
        raise HTTPException(422, "Filtro inválido")
    if project_id:
        projects = [get_project_or_404(project_id)]
    else:
        projects = db.fetch_all("SELECT * FROM projects WHERE source_path IS NOT NULL "
                                "ORDER BY created_at DESC LIMIT 10")
    for p in projects:
        try:
            src = storage.ensure_inside_root(p["source_path"]) if p.get("source_path") else None
        except storage.UnsafePathError:
            continue
        if not src or not src.is_file():
            continue
        clip = db.fetch_one("SELECT start FROM clips WHERE project_id = ? ORDER BY selected DESC, start LIMIT 1",
                            (p["id"],))
        at = (clip["start"] + 2.0) if clip else (p.get("source_duration") or 10) * 0.3
        try:
            out = color.preview(src, at, name, storage.root() / "tmp" / "filter_preview" / p["id"])
        except Exception:  # noqa: BLE001 — prévia é opcional; sem quadro, a interface mostra só o nome
            continue
        return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    raise HTTPException(404, "Nenhum vídeo disponível para a prévia")


# ------------------------------------------------------------------ preferências de edição
# escolhas padrão de cada projeto novo (aba "Preferências"); arquivo na pasta de dados
PREFERENCE_KEYS = (
    "caption_style", "layout", "pace", "speed", "cold_open", "title_style", "title_duration", "title_position",
    "color_filter", "transition", "zoom_fx", "flip_fx", "sfx", "censor", "engine", "hook", "zoom",
    "min_duration", "max_duration", "count", "series",
)


def _preferences_path():
    return storage.root() / "preferences.json"


@router.get("/preferences")
def get_preferences():
    import json

    p = _preferences_path()
    try:
        saved = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        saved = {}
    return {"options": saved, "saved": bool(saved)}


class PreferencesIn(BaseModel):
    options: dict


@router.put("/preferences")
def put_preferences(body: PreferencesIn):
    import json

    from .common import validate_options

    opts = validate_options(body.options)          # mesma validação de um projeto novo
    prefs = {k: opts[k] for k in PREFERENCE_KEYS if k in opts}
    _preferences_path().write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"options": prefs, "saved": True}


@router.delete("/preferences")
def delete_preferences():
    storage.remove_quietly(_preferences_path())
    return {"options": {}, "saved": False}
