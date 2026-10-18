"""Legendas dinâmicas em ASS (renderizadas pelo FFmpeg/libass).

- Agrupa palavras em blocos curtos (quebra inteligente: pontuação, pausas, limite de caracteres).
- Cada bloco gera um evento por palavra, com a palavra falada destacada (cor e/ou leve "pop").
- Posição na região central inferior, acima da área coberta pela interface do Shorts/Reels/TikTok.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pysubs2
from pysubs2 import Alignment, Color, SSAEvent, SSAFile, SSAStyle

from .textutil import STOPWORDS, clean_token


def hex_to_color(hex_str: str, alpha: int = 0) -> Color:
    h = hex_str.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"Cor inválida: {hex_str}")
    return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def ass_color(hex_str: str) -> str:
    """#RRGGBB → &HBBGGRR& (formato de override tag do ASS)."""
    h = hex_str.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


@dataclass
class CaptionStyle:
    name: str
    font: str
    size: int
    primary: str
    highlight: str
    outline_color: str
    outline: float
    shadow: float
    shadow_color: str = "#000000"
    uppercase: bool = False
    pop: bool = False
    keyword_color: str | None = None
    highlight_active: bool = True
    max_chars: int = 22
    max_words: int = 4
    glow: bool = False
    position: float = 0.30   # distância da base, como fração da altura
    italic: bool = False
    side_margin: float = 0.08  # margem lateral (fração da largura); maior = blocos em 2 linhas curtas
    names_color: str | None = None  # cor dos nomes próprios (ex.: "com Leo Dias")


PRESETS: dict[str, CaptionStyle] = {
    "classic": CaptionStyle("classic", "Poppins ExtraBold", 84, "#FFFFFF", "#FFD60A", "#000000", 6, 2),
    "neon": CaptionStyle("neon", "Poppins ExtraBold", 84, "#FFFFFF", "#B266FF", "#1A0033", 5, 0,
                         shadow_color="#7C3AED", pop=True, glow=True),
    "minimal": CaptionStyle("minimal", "Poppins Bold", 72, "#FFFFFF", "#FFFFFF", "#000000", 0, 3,
                            shadow_color="#000000", highlight_active=False, max_chars=28, max_words=5),
    "impact": CaptionStyle("impact", "Anton", 112, "#FFFFFF", "#FFD60A", "#000000", 7, 3, uppercase=True,
                           pop=True, keyword_color="#39FF88", max_chars=16, max_words=3),
    # estilo das páginas de cortes de podcast: amarelo em itálico, contorno grosso, nomes em vermelho,
    # blocos curtos em duas linhas, sem destaque palavra a palavra
    "amarela": CaptionStyle("amarela", "Poppins ExtraBold", 116, "#FFE11A", "#FFE11A", "#000000", 8, 2,
                            highlight_active=False, max_chars=20, max_words=4, italic=True, side_margin=0.2,
                            names_color="#FF2E2E", position=0.32),
}


def resolve_style(name: str, overrides: dict | None = None) -> CaptionStyle:
    base = PRESETS.get(name, PRESETS["classic"])
    style = CaptionStyle(**base.__dict__)
    for key in ("primary", "highlight", "outline_color", "keyword_color"):
        if overrides and overrides.get(key):
            hex_to_color(overrides[key])  # valida
            setattr(style, key, overrides[key])
    if overrides and overrides.get("size"):
        style.size = int(min(max(int(overrides["size"]), 40), 160))
    if overrides and overrides.get("position") is not None:
        style.position = float(min(max(float(overrides["position"]), 0.12), 0.6))
    return style


def group_words(words: list[dict], max_chars: int, max_words: int, max_gap: float = 0.6) -> list[list[dict]]:
    """Quebra inteligente: respeita pontuação, pausas e limite de tamanho do bloco."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        if cur:
            gap = w["start"] - cur[-1]["end"]
            length = sum(len(x["text"]) + 1 for x in cur) + len(w["text"])
            if gap > max_gap or length > max_chars or len(cur) >= max_words:
                groups.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"[.!?…;:]$", w["text"]) or (re.search(r",$", w["text"]) and len(cur) >= 2):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    # evita bloco final de uma palavra só "pendurada"
    merged: list[list[dict]] = []
    for g in groups:
        if (merged and len(g) == 1 and len(merged[-1]) < max_words
                and g[0]["start"] - merged[-1][-1]["end"] < 0.3
                and sum(len(x["text"]) + 1 for x in merged[-1]) + len(g[0]["text"]) <= max_chars + 4
                and not re.search(r"[.!?…]$", merged[-1][-1]["text"])):
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    return merged


def _is_keyword(token: str) -> bool:
    t = clean_token(token)
    return len(t) >= 6 and t not in STOPWORDS or any(ch.isdigit() for ch in t)


def _proper_names(words: list[dict]) -> set[int]:
    """Palavras com inicial maiúscula fora do começo de frase (nomes próprios), pelo id do dicionário."""
    out, prev = set(), ""
    for w in words:
        t = w["text"].strip()
        starts = not prev or prev.endswith((".", "!", "?", "…"))
        core = t.strip("“”\"'(),.!?…:;")
        if not starts and len(core) > 1 and core[0].isupper() and clean_token(core) not in STOPWORDS:
            out.add(id(w))
        prev = t
    return out


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def build_ass(words: list[dict], style: CaptionStyle, width: int, height: int, path: Path,
              centered: bool = False, below: tuple[float | None, int] | None = None) -> Path:
    """Gera o arquivo .ass. `words` devem estar no tempo do vídeo final (segundos).

    `centered=True` posiciona a legenda no meio da tela (usado no layout dividido,
    para a legenda ficar na divisão entre os dois participantes).
    `below=(até, y)` desce a legenda para abaixo de `y` (px) enquanto houver um título nessa
    região — até o segundo `até`, ou o vídeo inteiro se `até` for None.
    """
    subs = SSAFile()
    subs.info.update({"PlayResX": str(width), "PlayResY": str(height), "WrapStyle": "0",
                      "ScaledBorderAndShadow": "yes"})
    margin_v = int(height * style.position)
    s = SSAStyle(
        fontname=style.font, fontsize=style.size, primarycolor=hex_to_color(style.primary),
        secondarycolor=hex_to_color(style.highlight), outlinecolor=hex_to_color(style.outline_color),
        backcolor=hex_to_color(style.shadow_color, 96 if style.glow else 80), bold=False,
        outline=style.outline, shadow=style.shadow,
        alignment=Alignment.MIDDLE_CENTER if centered else Alignment.BOTTOM_CENTER,
        marginl=int(width * style.side_margin), marginr=int(width * style.side_margin),
        marginv=0 if centered else margin_v, borderstyle=1, italic=style.italic,
    )
    subs.styles["Caption"] = s
    if below:
        low = s.copy()
        low.alignment, low.marginv = Alignment.TOP_CENTER, below[1] + 24
        subs.styles["CaptionLow"] = low

    hl = ass_color(style.highlight)
    kw = ass_color(style.keyword_color) if style.keyword_color else None
    nc = ass_color(style.names_color) if style.names_color else None
    names = _proper_names(words) if nc else set()
    groups = group_words(words, style.max_chars, style.max_words)
    for gi, group in enumerate(groups):
        tokens = [w["text"].upper() if style.uppercase else w["text"] for w in group]
        g_end = group[-1]["end"] + 0.12
        if gi + 1 < len(groups):  # termina quando o próximo bloco começa (nunca dois blocos na tela)
            g_end = min(g_end, groups[gi + 1][0]["start"])
        for i, w in enumerate(group):
            start = w["start"]
            end = group[i + 1]["start"] if i + 1 < len(group) else g_end
            if end <= start:
                end = start + 0.05
            parts = []
            for j, tok in enumerate(tokens):
                tok = _escape(tok)
                if j == i and style.highlight_active:
                    anim = r"\t(0,90,\fscx112\fscy112)\t(90,180,\fscx100\fscy100)" if style.pop else ""
                    parts.append(f"{{\\c{hl}{anim}}}{tok}{{\\r}}")
                elif nc and id(group[j]) in names:
                    parts.append(f"{{\\c{nc}}}{tok}{{\\r}}")
                elif kw and _is_keyword(group[j]["text"]):
                    parts.append(f"{{\\c{kw}}}{tok}{{\\r}}")
                else:
                    parts.append(tok)
            prefix = r"{\blur3}" if style.glow else ""
            if i == 0:
                prefix += r"{\fad(60,0)}"
            low = below and (below[0] is None or group[0]["start"] < below[0])
            subs.append(SSAEvent(start=int(start * 1000), end=int(end * 1000),
                                 style="CaptionLow" if low else "Caption", text=prefix + " ".join(parts)))
    subs.save(str(path), encoding="utf-8")
    return path


def build_srt(words: list[dict], path: Path, max_chars: int = 42) -> Path:
    subs = SSAFile()
    for g in group_words(words, max_chars, 10, max_gap=0.8):
        subs.append(SSAEvent(start=int(g[0]["start"] * 1000), end=int(g[-1]["end"] * 1000),
                             text=" ".join(w["text"] for w in g)))
    subs.save(str(path), format_="srt", encoding="utf-8")
    return path


def ffmpeg_filter_path(path: Path) -> str:
    """Escapa um caminho para uso dentro de um filtro do FFmpeg (inclui Windows C:\\...)."""
    p = str(path).replace("\\", "/")
    p = p.replace(":", r"\:").replace("'", r"\'")
    return p


__all__ = ["PRESETS", "resolve_style", "group_words", "build_ass", "build_srt", "pysubs2"]
