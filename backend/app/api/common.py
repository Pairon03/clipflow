"""Funções compartilhadas pelas rotas."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .. import config, db, storage
from ..pipeline.color import FILTERS as _COLOR_FILTERS
from ..security import RIGHTS_BASES

STYLES = {
    "podcast_premium": {"label": "Podcast premium", "caption_style": "classic", "layout": "auto", "max_pause": 0.7},
    "entrevista": {"label": "Entrevista", "caption_style": "classic", "layout": "auto", "max_pause": 0.7},
    "motivacional": {"label": "Motivacional", "caption_style": "impact", "layout": "follow", "max_pause": 0.6},
    "educativo": {"label": "Educativo", "caption_style": "minimal", "layout": "follow", "max_pause": 0.8},
    "dinamico": {"label": "Dinâmico", "caption_style": "impact", "layout": "auto", "max_pause": 0.45},
}
CAPTION_STYLES = {"classic", "neon", "minimal", "impact"}
LAYOUTS = {"auto", "follow", "speaker", "split", "fit", "center", "manual"}
TITLE_STYLES = {"tweet", "caixa", "citacao", "variar", "nenhum"}
PACES = {"natural", "tiktok"}  # tiktok: corta respirações e silêncios entre falas
COLOR_FILTERS = set(_COLOR_FILTERS)  # filtros de cor (gradação) do vídeo
ENGINES = {"ffmpeg", "concat"}  # concat: zoom de ênfase, texto de gancho e exportação pelo Concat
MAX_CLIP_SECONDS = 180  # limite atual do YouTube Shorts


def not_found(what: str = "Item") -> HTTPException:
    return HTTPException(404, f"{what} não encontrado")


def get_project_or_404(pid: str) -> dict:
    try:
        storage.check_id(pid)
    except storage.UnsafePathError:
        raise not_found("Projeto")
    p = db.fetch_one("SELECT * FROM projects WHERE id = ?", (pid,))
    if not p:
        raise not_found("Projeto")
    return p


def get_clip_or_404(cid: str) -> dict:
    try:
        storage.check_id(cid)
    except storage.UnsafePathError:
        raise not_found("Corte")
    c = db.fetch_one("SELECT * FROM clips WHERE id = ?", (cid,))
    if not c:
        raise not_found("Corte")
    return c


def validate_options(raw: dict | None) -> dict:
    raw = dict(raw or {})
    style = raw.get("style") or "podcast_premium"
    if style not in STYLES:
        raise HTTPException(422, "Estilo inválido")
    preset = STYLES[style]
    max_clips = int(config.get("limits.max_clips_per_project"))
    try:
        count = int(raw.get("count", 5))
        min_d = float(raw.get("min_duration", 30))
        max_d = float(raw.get("max_duration", 60))
    except (TypeError, ValueError):
        raise HTTPException(422, "Quantidade/duração inválidas")
    if not 1 <= count <= max_clips:
        raise HTTPException(422, f"Quantidade de Shorts deve estar entre 1 e {max_clips}")
    if not (5 <= min_d < max_d <= MAX_CLIP_SECONDS):
        raise HTTPException(422, f"Duração deve ficar entre 5 e {MAX_CLIP_SECONDS} segundos (mínimo < máximo)")
    if max_d - min_d < 5:
        raise HTTPException(422, "A faixa de duração precisa ter pelo menos 5 segundos")
    caption_style = raw.get("caption_style") or preset["caption_style"]
    if caption_style not in CAPTION_STYLES:
        raise HTTPException(422, "Estilo de legenda inválido")
    layout = raw.get("layout") or preset["layout"]
    if layout not in LAYOUTS:
        raise HTTPException(422, "Enquadramento inválido")
    pace = raw.get("pace") or "tiktok"
    if pace not in PACES:
        raise HTTPException(422, "Ritmo inválido")
    try:
        speed = round(float(raw.get("speed", 1.0) or 1.0), 2)
    except (TypeError, ValueError):
        raise HTTPException(422, "Velocidade inválida")
    if not 1.0 <= speed <= 1.25:
        raise HTTPException(422, "Velocidade deve ficar entre 1.0x e 1.25x")
    title_style = raw.get("title_style")
    if title_style is None:  # compatibilidade com o antigo "theme"
        title_style = "tweet" if raw.get("theme", True) else "nenhum"
    if title_style not in TITLE_STYLES:
        raise HTTPException(422, "Estilo de título inválido")
    title_duration = raw.get("title_duration") or "inteiro"
    if title_duration not in {"inteiro", "inicio"}:
        raise HTTPException(422, "Duração do título inválida")
    title_position = raw.get("title_position") or "topo"
    if title_position not in {"topo", "meio"}:
        raise HTTPException(422, "Posição do título inválida")
    transition = raw.get("transition") or "zoom"
    if transition not in {"zoom", "flash", "fade", "nenhuma"}:
        raise HTTPException(422, "Transição inválida")
    sfx = raw.get("sfx") or "sutil"
    if sfx not in {"sutil", "normal", "nenhum"}:
        raise HTTPException(422, "Nível de efeitos sonoros inválido")
    censor = raw.get("censor") or "mudo"
    if censor not in {"mudo", "bip", "nenhum"}:
        raise HTTPException(422, "Modo de censura inválido")
    color_filter = raw.get("color_filter") or "nenhum"
    if color_filter not in COLOR_FILTERS:
        raise HTTPException(422, "Filtro de cor inválido")
    engine = raw.get("engine") or "ffmpeg"
    if engine not in ENGINES:
        raise HTTPException(422, "Motor de edição inválido")
    colors = {}
    for k in ("primary", "highlight", "outline_color", "keyword_color"):
        v = (raw.get("caption_colors") or {}).get(k)
        if v:
            import re

            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v)):
                raise HTTPException(422, f"Cor inválida: {v}")
            colors[k] = v
    for k in ("size", "position"):
        v = (raw.get("caption_colors") or {}).get(k)
        if v not in (None, ""):
            colors[k] = float(v)
    return {
        "style": style,
        "count": count,
        "min_duration": min_d,
        "max_duration": max_d,
        "caption_style": caption_style,
        "caption_colors": colors,
        "captions": bool(raw.get("captions", True)),
        "layout": layout,
        "trim_silence": bool(raw.get("trim_silence", True)),
        "max_pause": float(preset["max_pause"]),
        "review": bool(raw.get("review", False)),
        "engine": engine,
        "hook": bool(raw.get("hook", True)),
        "zoom": bool(raw.get("zoom", True)),
        "pace": pace,
        "speed": speed,
        "title_style": title_style,
        "title_duration": title_duration,
        "title_position": title_position,
        "cold_open": bool(raw.get("cold_open", True)),
        "color_filter": color_filter,
        "transition": transition,
        "zoom_fx": bool(raw.get("zoom_fx", True)),
        "sfx": sfx,
        "censor": censor,
    }


def public_path(path: str | None) -> Path | None:
    if not path:
        return None
    try:
        p = storage.ensure_inside_root(path)
    except storage.UnsafePathError:
        return None
    return p if p.exists() else None


def clip_public(c: dict) -> dict:
    out = {k: v for k, v in c.items() if k not in {"output_path", "thumb_path", "srt_path", "words"}}
    out["has_video"] = bool(c.get("output_path")) and c.get("status") == "done"
    out["has_thumb"] = bool(c.get("thumb_path"))
    out["edited_words"] = c.get("words") is not None
    out["duration_planned"] = round(c["end"] - c["start"], 2)
    return out


def project_public(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k != "source_path"}
    out["rights_label"] = RIGHTS_BASES.get(p["rights_basis"], p["rights_basis"])
    out["has_source"] = bool(public_path(p.get("source_path")))
    return out
