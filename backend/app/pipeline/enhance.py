"""Decisões de edição automática aplicadas no Concat: zoom de ênfase e texto de gancho.

Tudo é decidido a partir da própria fala (palavras com tempo no vídeo final), sem
inventar conteúdo: o gancho é um dos títulos sugeridos (que só usam frases reais) e
os zooms caem nos blocos de fala com mais marcas de ênfase.
"""
from __future__ import annotations

import re

from . import subtitles
from .textutil import MARKERS, clean_token, norm

ZOOM_SCALE = 1.12        # 12% de aproximação: perceptível sem cortar rostos
ZOOM_IN_S = 0.2
ZOOM_OUT_S = 0.3
MIN_GAP_S = 4.0          # distância mínima entre dois zooms
SECONDS_PER_ZOOM = 8.0   # no máximo um zoom a cada ~8 s de vídeo
HOOK_DURATION_S = 2.8

_EMPHASIS = [norm(m) for m in MARKERS["Frase de impacto"] + MARKERS["Emocionante"] + MARKERS["Curiosidade"]]


def _group_score(text: str) -> float:
    n = norm(text)
    score = sum(1.0 for m in _EMPHASIS if m in n)
    if "!" in text:
        score += 1.0
    if "?" in text:
        score += 0.6
    if re.search(r"\d", text):
        score += 0.6
    score += 0.15 * sum(1 for t in text.split() if len(clean_token(t)) >= 8)
    return score


def pick_zooms(words: list[dict], duration: float, skip_start: float = HOOK_DURATION_S) -> list[tuple[float, float]]:
    """Escolhe os trechos (início, fim) que recebem zoom de ênfase."""
    groups = subtitles.group_words(words, max_chars=28, max_words=5)
    scored = []
    for g in groups:
        s, e = g[0]["start"], g[-1]["end"]
        if s < skip_start or e > duration - 0.4 or e - s < 0.4:
            continue
        sc = _group_score(" ".join(w["text"] for w in g))
        if sc > 0:
            scored.append((sc, s, min(e, s + 2.5)))
    limit = max(1, int(duration // SECONDS_PER_ZOOM))
    chosen: list[tuple[float, float]] = []
    for sc, s, e in sorted(scored, key=lambda x: -x[0]):
        if len(chosen) >= limit:
            break
        if all(e + MIN_GAP_S <= cs or s >= ce + MIN_GAP_S for cs, ce in chosen):
            chosen.append((round(s, 3), round(e, 3)))
    return sorted(chosen)


def zoom_keyframes(zooms: list[tuple[float, float]], duration: float,
                   scale: float = ZOOM_SCALE) -> list[dict]:
    """Converte zooms em keyframes de escala do Concat (posição = fração do clipe, 0–1)."""
    ease_in = [0.25, 0.1, 0.25, 1.0]
    keys: list[dict] = []
    if not zooms or duration <= 0:
        return keys
    for s, e in zooms:
        pts = [
            (max(s - 0.05, 0.0), 1.0, None),
            (min(s + ZOOM_IN_S, duration), scale, ease_in),
            (min(e, duration), scale, None),
            (min(e + ZOOM_OUT_S, duration), 1.0, ease_in),
        ]
        for t, value, ease in pts:
            key = {"at": round(t / duration, 5), "value": value}
            if ease:
                key["ease"] = ease
            keys.append(key)
    keys.sort(key=lambda k: k["at"])
    out: list[dict] = []
    for k in keys:  # o Concat substitui chaves muito próximas; mantemos as posições distintas
        if out and k["at"] - out[-1]["at"] < 0.002:
            continue
        out.append(k)
    return out


def hook_text(titles: list[str], max_chars: int = 60, line_chars: int = 20) -> str | None:
    """Texto de gancho para os primeiros segundos: o melhor título, sem aspas, em até 3 linhas."""
    for t in titles or []:
        t = t.strip().strip("“”\"").rstrip("…").strip()
        if 8 <= len(t) <= max_chars:
            break
    else:
        return None
    lines, cur = [], ""
    for word in t.split():
        if cur and len(cur) + 1 + len(word) > line_chars:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    lines.append(cur)
    return "\n".join(lines[:3])


# ------------------------------------------------------------------ gancho de abertura e tema
COLD_OPEN_MIN_S = 1.5
COLD_OPEN_MAX_S = 4.5
COLD_OPEN_MIN_POS_S = 3.0   # a fala precisa estar mais para frente; se já é o início, não há o que antecipar


def pick_cold_open(words: list[dict], clip_start: float, clip_end: float) -> tuple[float, float] | None:
    """Escolhe a fala mais chamativa do corte para abrir o vídeo (antes do começo normal).

    Retorna (início, fim) relativos ao início do corte, ou None se nada se destacar.
    Só usa frases completas e curtas, para o gancho fazer sentido sozinho.
    """
    from .selection import build_sentences

    if clip_end - clip_start < 12 or len(words) < 6:
        return None
    from .textutil import keywords

    # palavras que mais aparecem no corte = assunto; frases com elas resumem melhor o trecho
    topic = {norm(k) for k in keywords(" ".join(w["text"] for w in words), top=6)}
    best, best_score = None, 0.0
    for s in build_sentences(words, max_sentence_s=COLD_OPEN_MAX_S):
        dur = s.end - s.start
        rel = s.start - clip_start
        if not (COLD_OPEN_MIN_S <= dur <= COLD_OPEN_MAX_S) or rel < COLD_OPEN_MIN_POS_S:
            continue
        if clip_end - s.end < 1.0:
            continue
        text = s.text
        score = _group_score(text)
        if text.rstrip().endswith("!"):
            score += 0.5
        score += 0.4 * sum(1 for t in text.split() if norm(clean_token(t)) in topic)
        if clean_token(s.words[0]["text"]) in {"e", "mas", "aí", "então", "porque", "que"}:
            score -= 1.0  # começa pendurado no que veio antes
        if score > best_score:
            best, best_score = (s.start, s.end), score
    if best is None or best_score < 0.6:
        return None
    a = max(best[0] - clip_start - 0.05, 0.0)
    b = min(best[1] - clip_start + 0.15, clip_end - clip_start)
    return round(a, 3), round(b, 3)


def theme_text(titles: list[str], max_chars: int = 42, line_chars: int = 16) -> str | None:
    """Tema curto para o centro da tela, em até 3 linhas, a partir do melhor título."""
    for t in titles or []:
        t = t.strip().strip("“”\"").rstrip("…").strip()
        if not t:
            continue
        if len(t) > max_chars:
            t = t[:max_chars].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
        return hook_text([t], max_chars=max_chars + 1, line_chars=line_chars)
    return None
