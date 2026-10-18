"""Palavrões: silencia (ou cobre com bipe) o áudio e mascara o texto nas legendas e títulos.

A lista cobre os palavrões mais comuns em português; dá para acrescentar palavras em
Configurações (censor.extra_words). Palavras ambíguas ("pau", "rola", "pica") ficam de fora
para não cortar falas normais.
"""
from __future__ import annotations

import re

from .. import config
from .textutil import norm

# formas exatas (já sem acento, minúsculas)
_EXACT = {
    "porra", "porras", "caralho", "caralhos", "caralha", "krl", "crl", "merda", "merdas", "merdinha",
    "puta", "putas", "puto", "putos", "putaria", "putinha", "putao", "pqp", "fdp", "vsf", "tnc", "vtnc",
    "buceta", "bucetas", "boceta", "cacete", "cu", "cus", "cuzao", "cuzinho", "bosta", "bostas",
    "viado", "viados", "viadinho", "viadagem", "arrombado", "arrombada", "arrombados", "piroca",
    "xoxota", "punheta", "punheteiro", "siririca", "escroto", "escrota", "corno", "cornos", "babaca",
    "otario", "otaria", "vagabunda", "desgracado", "desgracada", "fodase",
}
# prefixos seguros (não começam palavras comuns)
_PREFIXES = ("caralh", "fod", "porr", "punhet", "arromb", "bucet", "bocet")
_SAFE = {"fodder", "porrada", "porradas", "porrete"}  # começam com prefixo mas não são palavrão
MODES = {"mudo", "bip", "nenhum"}
PAD_S = 0.05


def _extra() -> set[str]:
    raw = config.get("censor.extra_words") or ""
    return {norm(w.strip()) for w in re.split(r"[,;\n]+", raw) if w.strip()}


def is_profane(token: str, extra: set[str] | None = None) -> bool:
    t = norm(re.sub(r"[^\wÀ-ÿ-]", "", token or "")).replace("-", "")
    if not t or t in _SAFE:
        return False
    if t in _EXACT or t in (extra if extra is not None else _extra()):
        return True
    return t.startswith(_PREFIXES)


def mask(token: str) -> str:
    """'porra,' → 'p****,' (mantém a 1ª letra e a pontuação)."""
    m = re.match(r"^(\W*)(\w)([\w-]*)(\W*)$", token)
    if not m:
        return "*" * len(token)
    return m.group(1) + m.group(2) + "*" * len(m.group(3)) + m.group(4)


def censor_words(words: list[dict]) -> tuple[list[dict], list[tuple[float, float]]]:
    """Mascara as palavras e devolve os intervalos (no tempo das palavras) a silenciar."""
    extra = _extra()
    out, spans = [], []
    for w in words:
        if is_profane(w["text"], extra):
            out.append(w | {"text": mask(w["text"])})
            a, b = max(w["start"] - PAD_S, 0.0), w["end"] + PAD_S
            if spans and a <= spans[-1][1]:
                spans[-1] = (spans[-1][0], round(b, 3))
            else:
                spans.append((round(a, 3), round(b, 3)))
        else:
            out.append(w)
    return out, spans


def censor_text(text: str) -> str:
    if not text:
        return text
    extra = _extra()
    return re.sub(r"[\wÀ-ÿ-]+", lambda m: mask(m.group(0)) if is_profane(m.group(0), extra) else m.group(0), text)


def censor_meta(meta: dict) -> dict:
    """Aplica a máscara em títulos, descrição, frase curta e partes do título sobreposto."""
    out = dict(meta)
    for k in ("description", "short_text"):
        if isinstance(out.get(k), str):
            out[k] = censor_text(out[k])
    if isinstance(out.get("titles"), list):
        out["titles"] = [censor_text(t) for t in out["titles"]]
    if isinstance(out.get("card"), dict):
        out["card"] = {k: censor_text(v) if isinstance(v, str) else v for k, v in out["card"].items()}
    return out


def mute_filter(spans: list[tuple[float, float]]) -> str | None:
    """Filtro de áudio que zera o volume nos intervalos (tempo do vídeo final)."""
    if not spans:
        return None
    cond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
    return f"volume=volume='if({cond},0,1)':eval=frame"
