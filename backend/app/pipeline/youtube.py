"""Obtenção de vídeos do YouTube com yt-dlp — somente para conteúdo com autorização de uso.

Política do ClipFlow Studio:
- Só vídeos públicos e individuais. Vídeos privados, com restrição de idade, de membros,
  pagos, ao vivo ou com DRM são recusados — sem cookies, sem contornar proteções.
- O usuário precisa declarar a base legal de uso antes do download (registrado no projeto).
- Lembre-se: os Termos do YouTube restringem downloads; use apenas para conteúdo seu ou
  quando o titular autorizou.
"""
from __future__ import annotations

from pathlib import Path

from .. import config
from ..security import canonical_youtube_url
from .context import JobContext
from .errors import FatalPipelineError, PipelineError

BLOCKED_AVAILABILITY = {"private", "premium_only", "subscriber_only", "needs_auth"}


def _ydl_base() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
        "cachedir": False,
        "extractor_retries": 2,
    }


def _import():
    try:
        import yt_dlp
    except ImportError as exc:
        raise FatalPipelineError("yt-dlp não está instalado (pip install yt-dlp)") from exc
    return yt_dlp


def _friendly(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "private" in low:
        return "Vídeo privado — não é possível processar."
    if "sign in" in low or "age" in low or "confirm your age" in low:
        return "Vídeo com restrição de acesso (login/idade). O ClipFlow não contorna restrições."
    if "unavailable" in low or "removed" in low:
        return "Vídeo indisponível."
    if "drm" in low:
        return "Vídeo protegido por DRM — não suportado."
    if "members" in low or "join this channel" in low:
        return "Vídeo exclusivo para membros — não suportado."
    return f"Não foi possível acessar o vídeo: {msg[:300]}"


def check_allowed(info: dict) -> None:
    if info.get("_type") == "playlist":
        raise FatalPipelineError("Links de playlist não são aceitos. Use o link de um vídeo.")
    if info.get("availability") in BLOCKED_AVAILABILITY:
        raise FatalPipelineError(f"Vídeo com acesso restrito ({info.get('availability')}).")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise FatalPipelineError("Transmissões ao vivo ou agendadas não são suportadas. Aguarde o fim da live.")
    if info.get("age_limit", 0) and info.get("age_limit", 0) >= 18:
        raise FatalPipelineError("Vídeo com restrição de idade — não suportado.")
    if info.get("has_drm"):
        raise FatalPipelineError("Vídeo protegido por DRM — não suportado.")
    max_min = config.get("limits.max_source_minutes")
    if info.get("duration") and info["duration"] > max_min * 60:
        raise FatalPipelineError(f"Vídeo maior que o limite configurado ({max_min} min).")


def fetch_metadata(video_id: str) -> dict:
    yt_dlp = _import()
    url = canonical_youtube_url(video_id)
    try:
        with yt_dlp.YoutubeDL(_ydl_base()) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise FatalPipelineError(_friendly(exc)) from exc
    if info is None:
        raise FatalPipelineError("Vídeo não encontrado.")
    check_allowed(info)
    return {
        "video_id": video_id,
        "url": url,
        "title": info.get("title") or video_id,
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "license": info.get("license") or "",
        "upload_date": info.get("upload_date") or "",
        "width": info.get("width"),
        "height": info.get("height"),
    }


def download(video_id: str, dest_dir: Path, ctx: JobContext) -> Path:
    yt_dlp = _import()
    url = canonical_youtube_url(video_id)

    def hook(d: dict) -> None:
        if ctx.cancelled():
            raise PipelineError("cancelado")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                ctx.progress(d.get("downloaded_bytes", 0) / total * 0.98)

    opts = _ydl_base() | {
        "skip_download": False,
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "progress_hooks": [hook],
        "max_filesize": config.get("limits.max_upload_mb") * 1024 * 1024,
        "overwrites": True,
        "retries": 3,
    }
    from .ffmpeg import _find

    if _find("ffmpeg"):
        opts["ffmpeg_location"] = str(Path(_find("ffmpeg")).parent)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            check_allowed(info)
    except FatalPipelineError:
        raise
    except Exception as exc:
        if ctx.cancelled():
            from .errors import Cancelled

            raise Cancelled() from exc
        raise PipelineError(_friendly(exc)) from exc
    files = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix not in {".part", ".ytdl"}]
    if not files:
        raise PipelineError("Download terminou sem gerar arquivo de vídeo")
    ctx.progress(1.0)
    return files[0]
