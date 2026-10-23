"""Séries (Parte 1, 2, 3…): uma história longa dividida em vídeos que terminam em suspense.

Páginas de cortes publicam a mesma história em partes: cada parte termina numa virada ("aí ele olhou pra mim
e falou…") e a seguinte retoma com a última frase da anterior. Aqui:

1. A história é um bloco do mapa do episódio (pipeline/episode.py) maior que a duração máxima de um corte.
2. Os pontos de corte só caem em fim de frase e são escolhidos por programação dinâmica: cada parte dentro da
   duração pedida, perto do alvo, e terminando no melhor "gancho de continuação" possível (pergunta, frase de
   tensão, pausa antes de uma virada como "aí", "só que", "quando eu vi").
3. Da Parte 2 em diante, a última frase da parte anterior abre o vídeo como retomada (fala real, nada inventado).
"""
from __future__ import annotations

import math
import re

from .selection import Sentence
from .textutil import DEPENDENT_ENDINGS, clean_token, norm

MAX_PARTS = 5
PART_COST = 1.2
RECAP_MAX_S = 8.0
TENSION_RE = re.compile(r"\b(de repente|quando eu vi|sabe o que|adivinha|ai ele|ai ela|so que|ai eu|"
                        r"do nada|nao acreditei|olhou pra mim|falou assim|virou pra mim)\b")
TURN_STARTS = ("ai ", "so que", "mas ", "quando ", "entao ", "de repente", "do nada", "e ai", "na hora")


def cut_quality(sents: list[Sentence], i: int) -> float:
    """Quão bom é terminar uma parte depois da frase i (suspense + corte limpo)."""
    s = sents[i]
    q = 0.0
    if s.complete:
        q += 0.3
    last = clean_token(s.words[-1]["text"]) if s.words else ""
    if last in DEPENDENT_ENDINGS:
        q -= 1.0                                  # "…e", "…que": parte cortada no meio da ideia
    if s.is_question:
        q += 0.6                                  # pergunta sem resposta: o público quer a próxima parte
    t = norm(s.text)
    if TENSION_RE.search(t[-60:]):
        q += 0.4
    if i + 1 < len(sents):
        nxt = norm(sents[i + 1].text).lstrip(" ,.")
        if nxt.startswith(TURN_STARTS):
            q += 0.4                              # a próxima parte começa na virada
        q += 0.3 * min(1.0, s.gap_after / 1.0)
    return q


def plan(sents: list[Sentence], min_s: float, max_s: float) -> list[dict]:
    """Divide as frases de uma história em partes. Devolve [{start, end, first, last, recap}] ou [] se não couber.

    `recap` é o intervalo (start, end) da frase repetida no começo da parte (None na Parte 1).
    """
    n = len(sents)
    if n < 2:
        return []
    total = sents[-1].end - sents[0].start
    if total <= max_s:
        return []
    target = min(max_s * 0.9, max(min_s, total / math.ceil(total / (max_s * 0.9))))

    def recap_of(prev_last: int) -> tuple[float, float] | None:
        s = sents[prev_last]
        return (s.start, s.end) if s.end - s.start <= RECAP_MAX_S else None

    def dur(first: int, last: int, prev_last: int | None) -> float:
        start = sents[first].start
        if prev_last is not None and (r := recap_of(prev_last)):
            start = r[0]
        return sents[last].end - start

    # best[j] = (custo, partes) para partes cobrindo as frases 0..j
    inf = float("inf")
    best: list[tuple[float, list[tuple[int, int]]]] = [(inf, [])] * n
    for j in range(n):
        for i in range(j + 1):
            prev = best[i - 1] if i > 0 else (0.0, [])
            if prev[0] == inf or len(prev[1]) >= MAX_PARTS:
                continue
            prev_last = prev[1][-1][1] if prev[1] else None
            d = dur(i, j, prev_last)
            if d > max_s:
                continue
            if d < min_s and not (j == n - 1 and d >= min(min_s, 15.0) and prev[1]):
                continue                          # a última parte pode ser um pouco mais curta
            # cada parte nova custa caro: o suspense escolhe ONDE cortar, não faz cortar mais vezes
            ending = 0.0 if j == n - 1 else -0.6 * cut_quality(sents, j)
            cost = prev[0] + 1.5 * abs(d - target) / target + ending + PART_COST
            if cost < best[j][0]:
                best[j] = (cost, prev[1] + [(i, j)])
    parts = best[n - 1][1]
    if len(parts) < 2:
        return []
    out = []
    for k, (i, j) in enumerate(parts):
        recap = recap_of(parts[k - 1][1]) if k else None
        out.append({"start": recap[0] if recap else sents[i].start, "end": sents[j].end, "first": i, "last": j,
                    "recap": recap, "cliff": round(cut_quality(sents, j), 2) if k < len(parts) - 1 else None})
    return out


def part_title(base: str, part: int, total: int, limit: int = 100) -> str:
    suffix = f" (Parte {part}/{total})"
    base = re.sub(r"\s*\(Parte \d+/\d+\)\s*$", "", base or "").strip()
    return (base[: limit - len(suffix)].rstrip() + suffix) if base else suffix.strip()


def part_description(description: str, part: int, total: int) -> str:
    if part < total:
        line = f"📺 Parte {part} de {total}. A continuação está no próximo vídeo do perfil 👇"
    else:
        line = f"📺 Parte final ({part} de {total}). Veja as partes anteriores no perfil."
    return f"{line}\n\n{description}".strip()


# ------------------------------------------------------------------ quando vale a pena virar série
AUTO_MAX_SERIES = 2
AUTO_MIN_BLOCK_SCORE = 75.0
AUTO_MIN_CLIFF = 0.5


def worth_it(block, parts: list[dict], max_s: float) -> tuple[bool, str]:
    """Nem toda história vira série: só as fortes, longas demais para um corte e com bons pontos de suspense."""
    if not parts or not 2 <= len(parts) <= 4:
        return False, "não divide bem em 2 a 4 partes"
    if block.duration < max_s * 1.25:
        return False, "cabe em um corte só"
    if block.score < AUTO_MIN_BLOCK_SCORE:
        return False, "nota do bloco baixa"
    ai = block.ai or {}
    if ai:
        if not ai.get("tem_desfecho") or ai.get("nota", 0) < 65:
            return False, "a IA não viu uma história com desfecho"
    elif block.kind != "História":
        return False, "não parece uma história"
    cliffs = [p["cliff"] for p in parts if p.get("cliff") is not None]
    if cliffs and sum(cliffs) / len(cliffs) < AUTO_MIN_CLIFF:
        return False, "sem bons pontos de suspense entre as partes"
    return True, "história forte e longa, com suspense entre as partes"
