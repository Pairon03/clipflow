"""Filtros de cor (gradação) aplicados ao vídeo do Short, antes do título e da legenda.

São ajustes estéticos de cor, contraste e vinheta — a identidade visual do canal.
Não mudam o conteúdo nem servem para esconder a origem do vídeo.
"""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg

# chave → (nome na interface, cadeia de filtros do FFmpeg)
FILTERS: dict[str, tuple[str, str | None]] = {
    "nenhum": ("Original", None),
    "vivo": ("Vivo", "eq=contrast=1.08:saturation=1.3:brightness=0.01,unsharp=5:5:0.5"),
    "quente": ("Quente", "colorbalance=rs=0.12:bs=-0.12:rm=0.08:bm=-0.08:rh=0.04:bh=-0.05,"
                         "eq=contrast=1.05:saturation=1.12"),
    "frio": ("Frio", "colorbalance=rs=-0.1:bs=0.12:rm=-0.07:bm=0.1:rh=-0.03:bh=0.05,"
                     "eq=contrast=1.06:saturation=1.05"),
    "cinema": ("Cinema", "colorbalance=rs=-0.08:gs=-0.02:bs=0.1:rh=0.1:gh=0.03:bh=-0.08,"
                         "eq=contrast=1.12:saturation=1.15,vignette=PI/5"),
    "vintage": ("Vintage", "curves=preset=vintage,eq=saturation=0.85,vignette=PI/4"),
    "pb": ("Preto e branco", "hue=s=0,eq=contrast=1.2:brightness=0.02"),
}


def chain(name: str | None) -> str | None:
    """Cadeia de filtros do FFmpeg para o filtro escolhido (None = sem filtro)."""
    return FILTERS.get(name or "nenhum", (None, None))[1]


def preview(src: Path, at: float, name: str, cache_dir: Path) -> Path:
    """Quadro vertical (9:16) do vídeo com o filtro aplicado, para escolher na interface.

    O quadro base é extraído uma vez; cada filtro é aplicado sobre ele (rápido).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    base = cache_dir / "base.jpg"
    if not base.is_file():
        ffmpeg.run(["-ss", f"{max(at, 0):.2f}", "-i", str(src), "-frames:v", "1",
                    "-vf", "crop='min(iw,ih*9/16)':ih,scale=270:480", "-q:v", "3", str(base)], timeout=60)
    out = cache_dir / f"{name}.jpg"
    if not out.is_file():
        vf = chain(name)
        ffmpeg.run(["-i", str(base), "-frames:v", "1", *(["-vf", vf] if vf else []), "-q:v", "3", str(out)],
                   timeout=60)
    return out
