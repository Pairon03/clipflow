"""Títulos no estilo dos cortes profissionais, desenhados como imagem e sobrepostos ao vídeo.

Estilos:
- "tweet":   cartão branco no topo, como um post — avatar, nome e @ do SEU canal, e o resumo do trecho.
- "caixa":   caixa branca com barra colorida à esquerda e texto preto (ex.: "Fulano explica: ...").
- "citacao": ícone de aspas e a frase com fundo branco por linha, em caixa alta.

O cartão de tweet usa a identidade do canal configurado em Configurações (nunca a do convidado),
para não parecer uma postagem real de outra pessoa.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config

STYLES = {"tweet", "caixa", "citacao", "nenhum"}
ROTATION = ("tweet", "caixa", "citacao")  # estilo "variar": cada corte abre com um tema diferente


def resolve_style(style: str, clip_id: str, index: int | None = None) -> str:
    """'variar' alterna os estilos entre os cortes (pela ordem, ou pelo id se a ordem não for conhecida)."""
    if style != "variar":
        return style if style in STYLES else "nenhum"
    i = index if index is not None else sum(map(ord, clip_id or ""))
    return ROTATION[i % len(ROTATION)]
ACCENT = (124, 58, 237)      # roxo do ClipFlow
QUOTE_GREEN = (43, 217, 159)
_EMOJI_RE = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(config.FONTS_DIR / name), size)


def clean_text(text: str) -> str:
    """Remove emojis (as fontes não têm) e espaços duplicados."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in _EMOJI_RE.sub("", text or "").split("\n")]
    return "\n".join(line for line in lines if line)


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list[str]:
    """Quebra em linhas que cabem em `max_w`; respeita quebras manuais (\n)."""
    if "\n" in text:
        lines: list[str] = []
        for para in text.split("\n"):
            lines += wrap(para, font, max_w, max_lines)
        return _limit(lines, font, max_w, max_lines)
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return _limit(lines, font, max_w, max_lines)


def _limit(lines: list[str], font: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list[str]:
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.getlength(last + "…") > max_w:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last.rstrip(",;:") + "…"
    return lines


def _avatar(size: int, name: str, avatar_path: Path | None) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    if avatar_path and avatar_path.is_file():
        img = Image.open(avatar_path).convert("RGB")
        s = min(img.size)
        img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2))
        img = img.resize((size, size), Image.LANCZOS)
    else:
        img = Image.new("RGB", (size, size), ACCENT)
        initials = "".join(p[0] for p in clean_text(name).split()[:2]).upper() or "C"
        f = _font("Poppins-Bold.ttf", int(size * 0.4))
        d = ImageDraw.Draw(img)
        w = f.getlength(initials)
        d.text(((size - w) / 2, size * 0.27), initials, font=f, fill="white")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _shadow(canvas: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 10, x1, y1 + 10), radius, fill=(0, 0, 0, 110))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))


def tweet_card(text: str, channel: str, handle: str, avatar: Path | None, width: int, height: int,
               y: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    margin, pad, av = int(width * 0.055), 38, 92
    card_w = width - 2 * margin
    f_name, f_handle, f_text = _font("Poppins-SemiBold.ttf", 40), _font("Poppins-Medium.ttf", 33), \
        _font("Poppins-Medium.ttf", 47)
    lines = wrap(text, f_text, card_w - 2 * pad, 4)
    line_h = 64
    card_h = pad + av + 22 + len(lines) * line_h + pad - 8
    box = (margin, y, margin + card_w, y + card_h)
    _shadow(canvas, box, 34)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(box, 34, fill=(255, 255, 255, 255))
    canvas.alpha_composite(_avatar(av, channel, avatar), (margin + pad, y + pad))
    tx = margin + pad + av + 22
    d.text((tx, y + pad + 4), clean_text(channel)[:28], font=f_name, fill=(15, 20, 25))
    d.text((tx, y + pad + 50), clean_text(handle)[:30], font=f_handle, fill=(83, 100, 113))
    ty = y + pad + av + 18
    for line in lines:
        d.text((margin + pad, ty), line, font=f_text, fill=(15, 20, 25))
        ty += line_h
    return canvas


def box_card(text: str, width: int, height: int, y: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    margin, pad, bar = int(width * 0.065), 30, 24
    f = _font("Poppins-SemiBold.ttf", 56)
    max_w = width - 2 * margin - bar - 2 * pad
    lines = wrap(text, f, max_w, 3)
    line_h = 74
    text_w = max(int(f.getlength(l)) for l in lines)
    box = (margin + bar, y, margin + bar + text_w + 2 * pad, y + len(lines) * line_h + 2 * pad - 10)
    _shadow(canvas, (margin, box[1], box[2], box[3]), 6)
    d = ImageDraw.Draw(canvas)
    d.rectangle((margin, box[1], margin + bar, box[3]), fill=ACCENT + (255,))
    d.rectangle(box, fill=(255, 255, 255, 255))
    ty = y + pad - 6
    for line in lines:
        d.text((box[0] + pad, ty), line, font=f, fill=(10, 10, 10))
        ty += line_h
    return canvas


def quote_card(text: str, width: int, height: int, y: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    margin = int(width * 0.085)
    d = ImageDraw.Draw(canvas)
    icon = 86
    d.rounded_rectangle((margin, y, margin + icon, y + icon), 12, fill=QUOTE_GREEN + (255,))
    fq = _font("Poppins-ExtraBold.ttf", 120)
    d.text((margin + 15, y - 22), "“", font=fq, fill="white")
    f = _font("Poppins-ExtraBold.ttf", 54)
    lines = wrap(f"\"{text.upper()}\"", f, width - 2 * margin - 28, 4)
    ty, line_h, pad = y + icon + 22, 78, 14
    for line in lines:
        w = int(f.getlength(line))
        d.rectangle((margin, ty, margin + w + 2 * pad, ty + line_h - 8), fill=(255, 255, 255, 255))
        d.text((margin + pad, ty + 2), line, font=f, fill=(10, 10, 10))
        ty += line_h
    return canvas


def card_text(style: str, card: dict) -> str | None:
    """Escolhe o texto de cada estilo a partir das partes geradas pelo metadata."""
    lead, quote, question = card.get("lead") or "", card.get("quote") or "", card.get("question") or ""
    if style == "tweet":
        if config.get("branding.tweet_mode") != "resumo" and (config.get("branding.tweet_text") or "").strip():
            return config.get("branding.tweet_text").strip()
        return card.get("headline") or (f"{lead} “{quote}”".strip() if quote else lead) or None
    if style == "caixa":
        guest = card.get("guest")
        if question:
            head = f"{guest} responde:" if guest else "Pergunta:"
            return f"{head}\n{question}"
        return f"{lead}\n{quote}" if quote else (lead or None)
    if style == "citacao":
        return quote or question or None
    return None


def render_card(style: str, card: dict, out: Path, width: int, height: int, position: str = "top") -> Path | None:
    """Gera um PNG transparente do tamanho do vídeo com o título desenhado. None se não houver texto."""
    if style not in STYLES or style == "nenhum":
        return None
    text = clean_text(card_text(style, card) or "")
    if not text:
        return None
    # topo: abaixo da área da interface do TikTok/Shorts; "middle": na divisão do layout dividido
    y = int(height * 0.085) if position == "top" else int(height * 0.42)
    if style == "tweet":
        from . import branding

        b = branding.current()
        img = tweet_card(text, b["name"], b["handle"], b["avatar"], width, height, y)
    elif style == "caixa":
        img = box_card(text, width, height, y + 40)
    else:
        img = quote_card(text, width, height, y + 20)
    img.save(out, "PNG", optimize=True)
    return out
