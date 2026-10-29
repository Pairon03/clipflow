"""Estilo viral (opcional): as quatro dicas de gancho aplicadas a um corte.

1. Manchete de gancho: texto gigante e colorido nos primeiros segundos, sempre tirado da própria fala
   (pergunta, frase forte ou manchete da IA validada contra a transcrição) — nada inventado.
2. Entrada com movimento: "soco" de zoom no primeiro segundo.
3. Dinamismo: enquadramento muda a cada frase (aberto / fechado / fechado de lado), como outra câmera.
4. Chamada final: pergunta para comentar nos últimos segundos (ou "continua na Parte N" nas séries).
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from .overlay import _font, clean_text

HEADLINE_S = 2.6
CTA_S = 3.0
PUNCH_S = 0.6
PUNCH_SCALE = 0.30
DYNAMISM = {
    # intervalo mínimo entre trocas (s) e enquadramentos (zoom, centro x, centro y) usados em ciclo
    "medio": (3.2, [(1.0, 0.5, 0.40), (1.16, 0.5, 0.36), (1.10, 0.43, 0.40), (1.16, 0.57, 0.36)]),
    "alto": (2.2, [(1.0, 0.5, 0.40), (1.24, 0.5, 0.34), (1.12, 0.42, 0.40), (1.24, 0.58, 0.34)]),
}
WHITE, YELLOW = (255, 255, 255, 255), (255, 214, 10, 255)
_CTAS = {
    "Opinião": "VOCÊ CONCORDA?", "Pergunta e resposta": "E VOCÊ, O QUE ACHA?", "História": "JÁ PASSOU POR ISSO?",
    "Emocionante": "O QUE VOCÊ SENTIU?", "Educativo": "VOCÊ JÁ SABIA?", "Curiosidade": "VOCÊ JÁ SABIA?",
    "Frase de impacto": "CONCORDA?",
}


# ------------------------------------------------------------------ textos
def headline_text(card: dict | None, max_words: int = 9) -> str | None:
    """Manchete a partir das partes do título (só fala real ou manchete da IA já validada)."""
    card = card or {}
    for key in ("question", "headline", "quote", "topic_line"):
        t = clean_text(str(card.get(key) or "")).strip().strip("“”\"").rstrip(".…")
        if key == "headline":
            t = re.sub(r"^[^:]{1,40}:\s*", "", t).strip().strip("“”\"")      # "Fulano diz: “…”" → só a frase
        if not t or len(t) < 8:
            continue
        words = t.split()
        if len(words) > max_words:
            if key in ("question", "quote"):
                continue                                                   # não corta fala no meio
            t = " ".join(words[:max_words])
        return t.upper()
    return None


def cta_text(category: str | None, part: int | None = None, total: int | None = None) -> str:
    if part and total and part < total:
        return f"CONTINUA NA\nPARTE {part + 1}"
    return f"{_CTAS.get(category or '', 'O QUE VOCÊ ACHOU?')}\nCOMENTA AQUI"


# ------------------------------------------------------------------ imagens
def _wrap(text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if cur and font.getlength(cand) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def big_text_png(text: str, out: Path, width: int, height: int, y_center: float = 0.25) -> Path:
    """PNG do tamanho do vídeo com texto grande (linhas alternando branco/amarelo), contorno e sombra."""
    margin = int(width * 0.06)
    paragraphs = [p for p in text.split("\n") if p.strip()]
    for size in (124, 112, 100, 90, 80, 72):
        f = _font("Poppins-ExtraBold.ttf", size)
        lines = [ln for p in paragraphs for ln in _wrap(p, f, width - 2 * margin)]
        if len(lines) <= 4 and all(f.getlength(ln) <= width - 2 * margin for ln in lines):
            break
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = max(6, size // 11)
    lh = int(size * 1.08)
    y = int(height * y_center - lh * len(lines) / 2)
    for i, line in enumerate(lines):
        w = f.getlength(line)
        x = (width - w) / 2
        d.text((x + 6, y + 9), line, font=f, fill=(0, 0, 0, 140), stroke_width=stroke, stroke_fill=(0, 0, 0, 140))
        d.text((x, y), line, font=f, fill=WHITE if i % 2 == 0 else YELLOW, stroke_width=stroke,
               stroke_fill=(0, 0, 0, 255))
        y += lh
    img.save(out)
    return out


# ------------------------------------------------------------------ dinamismo
_END_RE = re.compile(r"[.!?…]$")


def angle_changes(words: list[dict], duration: float, level: str, start_after: float = 0.0) -> list[float]:
    """Instantes de troca de enquadramento: fim de frase (pontuação ou pausa), com intervalo mínimo."""
    if level not in DYNAMISM:
        return []
    min_gap = DYNAMISM[level][0]
    out: list[float] = []
    last = max(start_after, 0.8)
    for i, w in enumerate(words[:-1]):
        nxt = words[i + 1]
        boundary = _END_RE.search(w["text"].strip()) or nxt["start"] - w["end"] >= 0.35
        t = (w["end"] + nxt["start"]) / 2
        if boundary and t - last >= min_gap and t < duration - 1.5:
            out.append(round(t, 3))
            last = t
    # fala corrida sem pontuação: força uma troca a cada ~2× o intervalo mínimo
    filled, prev = [], max(start_after, 0.8)
    for t in out + [duration - 1.5]:
        while t - prev > 2 * min_gap + 0.5:
            prev += 1.5 * min_gap
            filled.append(round(prev, 3))
        if t < duration - 1.5:
            filled.append(t)
        prev = t
    return sorted(set(filled))


def _piecewise(times: list[float], values: list[float], default: float) -> str:
    expr = f"{default:g}"
    for t, v in zip(times, values):
        expr = f"if(gte(t,{t:.3f}),{v:g},{expr})"
    return expr


def framing_exprs(changes: list[float], level: str) -> tuple[str, str, str] | None:
    """Expressões FFmpeg (zoom, centro x, centro y) por tempo para os enquadramentos em ciclo."""
    if not changes or level not in DYNAMISM:
        return None
    framings = DYNAMISM[level][1]
    picks = [framings[(k + 1) % len(framings)] for k in range(len(changes))]
    z0, x0, y0 = framings[0]
    return (_piecewise(changes, [p[0] for p in picks], z0), _piecewise(changes, [p[1] for p in picks], x0),
            _piecewise(changes, [p[2] for p in picks], y0))
