"""Identidade do canal do usuário (nome, @ e avatar) usada no cartão de título estilo tweet."""
from __future__ import annotations

import re
from pathlib import Path

from .. import config

DEFAULT_NAME = "Meu Canal de Cortes"
DEFAULT_HANDLE = "@meucanal"


def avatar_path() -> Path:
    d = config.data_dir() / "branding"
    d.mkdir(parents=True, exist_ok=True)
    return d / "avatar.png"


def normalize_handle(handle: str) -> str:
    h = re.sub(r"[^A-Za-z0-9_.]", "", (handle or "").lstrip("@"))[:30]
    return f"@{h}" if h else ""


def current() -> dict:
    name = (config.get("branding.channel_name") or "").strip() or DEFAULT_NAME
    handle = normalize_handle(config.get("branding.channel_handle") or "") or DEFAULT_HANDLE
    av = avatar_path()
    return {"name": name, "handle": handle, "avatar": av if av.is_file() else None,
            "configured": bool((config.get("branding.channel_name") or "").strip())}


def save_avatar(data: bytes) -> Path:
    """Valida e salva o avatar (qualquer imagem comum), recortado em quadrado de 256 px."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Imagem inválida (use PNG ou JPG)") from exc
    s = min(img.size)
    img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2))
    img = img.resize((256, 256), Image.LANCZOS)
    out = avatar_path()
    img.save(out, "PNG")
    return out
