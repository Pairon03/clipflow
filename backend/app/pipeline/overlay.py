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

STYLES = {"tweet", "caixa", "citacao", "faixa", "nenhum"}
BAND_FRAC = 0.24  # "faixa": altura da faixa branca no topo; o vídeo fica abaixo dela
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


def band_height(height: int) -> int:
    return int(height * BAND_FRAC) // 2 * 2


def band_card(text: str, width: int, height: int) -> Image.Image:
    """Faixa branca no topo com a chamada em caixa alta, preta e centralizada."""
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    band = band_height(height)
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, width, band), fill=(255, 255, 255, 255))
    margin = int(width * 0.08)
    for size in (64, 58, 52, 46):                      # diminui a fonte até caber em 3 linhas
        f = _font("Poppins-Bold.ttf", size)
        lines = wrap(text.upper(), f, width - 2 * margin, 3)
        if not lines[-1].endswith("…"):
            break
    line_h = int(size * 1.22)
    ty = (band - line_h * len(lines)) // 2 + int(size * 0.05)
    for line in lines:
        w = f.getlength(line)
        d.text(((width - w) / 2, ty), line, font=f, fill=(10, 10, 10))
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
        if quote:
            return f"{lead}\n{quote}"
        return card.get("topic_line") or None      # sem frase boa: o assunto, nunca uma frase solta
    if style == "citacao":
        return quote or question or None
    if style == "faixa":
        return card.get("headline") or card.get("topic_line") or None
    return None


POSITIONS = {"top", "center", "split"}


def render_card(style: str, card: dict, out: Path, width: int, height: int, position: str = "top") -> Path | None:
    """Gera um PNG transparente do tamanho do vídeo com o título desenhado. None se não houver texto.

    `position`: "top" (abaixo da interface do TikTok/Shorts), "center" (meio da tela, um pouco acima
    da legenda) ou "split" (na divisão do layout dividido).
    """
    if style not in STYLES or style == "nenhum":
        return None
    text = clean_text(card_text(style, card) or "")
    if not text:
        return None
    y = int(height * 0.085)
    if style == "tweet":
        from . import branding

        b = branding.current()
        img = tweet_card(text, b["name"], b["handle"], b["avatar"], width, height, y)
    elif style == "faixa":
        img = band_card(text, width, height)
        position = "top"                              # a faixa é sempre no topo
    elif style == "caixa":
        img = box_card(text, width, height, y + 40)
    else:
        img = quote_card(text, width, height, y + 20)
    if position in ("center", "split"):
        bbox = img.getchannel("A").getbbox()
        if bbox:
            mid = height * (0.45 if position == "center" else 0.5)
            shift = int(mid - (bbox[1] + bbox[3]) / 2)
            moved = Image.new("RGBA", img.size, (0, 0, 0, 0))
            moved.paste(img, (0, shift))
            img = moved
    img.save(out, "PNG", optimize=True)
    return out


def series_tag(label: str, width: int) -> Image.Image:
    """Tarja vermelha "PARTE 2/3" (séries)."""
    f = _font("Poppins-ExtraBold.ttf", int(width * 0.042))
    pad_x, pad_y = int(width * 0.03), int(width * 0.014)
    tw = int(f.getlength(label))
    asc, desc = f.getmetrics()
    w, h = tw + 2 * pad_x, asc + desc + 2 * pad_y
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 3, fill=(229, 30, 42, 245))
    d.text((pad_x, pad_y - int(desc * 0.2)), label, font=f, fill=(255, 255, 255))
    return img


def add_series_tag(card_png: Path | None, label: str, out: Path, width: int, height: int, band: int = 0) -> Path:
    """Desenha a tarja da série logo abaixo do título (ou no topo, se não houver título) e devolve o PNG."""
    if card_png and Path(card_png).is_file():
        with Image.open(card_png) as im:
            canvas = im.convert("RGBA")
    else:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tag = series_tag(label, width)
    margin = int(width * 0.06)
    if band:
        y = band + int(height * 0.015)
    else:
        bbox = canvas.getchannel("A").getbbox()
        y = (bbox[3] + int(height * 0.012)) if bbox and bbox[1] < height * 0.5 else int(height * 0.085)
    canvas.alpha_composite(tag, (width - margin - tag.width, min(y, height - tag.height - margin)))
    out = Path(out)
    canvas.save(out)
    return out
