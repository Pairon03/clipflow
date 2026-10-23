"""Seleção inteligente de cortes a partir da transcrição.

1. As palavras são agrupadas em frases (pontuação final ou pausa longa).
2. Candidatos = sequências de frases completas com duração dentro da faixa pedida
   (nunca começam ou terminam no meio de uma frase).
3. Cada candidato recebe notas de 0 a 1 em sete critérios; a pontuação editorial
   (0–100) é a média ponderada. É uma ESTIMATIVA de qualidade editorial, não uma
   previsão de visualizações.
4. A seleção escolhe os melhores sem sobreposição; os demais viram alternativas
   que o usuário pode usar para substituir sugestões na revisão.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import audio as audio_mod
from .textutil import (CONTEXT_REFERENCES, DEPENDENT_ENDINGS, DEPENDENT_PHRASES, DEPENDENT_STARTERS, HOOK_STARTERS,
                       MARKERS, clean_token, norm)

WEIGHTS = {
    "clareza": 0.15,
    "independencia": 0.20,
    "interesse": 0.20,
    "retencao": 0.15,
    "audio": 0.10,
    "coerencia": 0.12,
    "cortes_suaves": 0.08,
}
LABELS = {
    "clareza": "Clareza",
    "independencia": "Independência de contexto",
    "interesse": "Interesse narrativo",
    "retencao": "Potencial de retenção",
    "audio": "Qualidade do áudio",
    "coerencia": "Coerência da fala",
    "cortes_suaves": "Ausência de cortes abruptos",
}

SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*$")
PAUSE_SPLIT_S = 0.9


@dataclass
class Sentence:
    start: float
    end: float
    words: list[dict]
    gap_before: float = 0.0
    gap_after: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)

    @property
    def is_question(self) -> bool:
        return self.text.rstrip().endswith("?")

    @property
    def complete(self) -> bool:
        return bool(SENTENCE_END.search(self.words[-1]["text"]))


@dataclass(eq=False)
class Candidate:
    start: float
    end: float
    sentences: list[Sentence]
    scores: dict = field(default_factory=dict)
    score: float = 0.0
    category: str = ""
    reasons: list[str] = field(default_factory=list)
    block: int | None = None            # bloco do mapa do episódio (pipeline/episode.py)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def words(self) -> list[dict]:
        return [w for s in self.sentences for w in s.words]

    def as_dict(self) -> dict:
        return {
            "start": round(self.start, 3), "end": round(self.end, 3), "text": self.text,
            "score": round(self.score, 1), "scores": {k: round(v, 3) for k, v in self.scores.items()},
            "category": self.category, "reasons": self.reasons, "block": self.block,
        }


def build_sentences(words: list[dict], max_sentence_s: float = 25.0) -> list[Sentence]:
    sentences: list[Sentence] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 99.0
        if SENTENCE_END.search(w["text"]) or gap >= PAUSE_SPLIT_S or nxt is None:
            sentences.extend(_split_long(cur, max_sentence_s))
            cur = []
    for i, s in enumerate(sentences):
        s.gap_before = s.start - sentences[i - 1].end if i > 0 else s.start
        s.gap_after = sentences[i + 1].start - s.end if i + 1 < len(sentences) else 5.0
    return sentences


def _split_long(words: list[dict], max_s: float) -> list[Sentence]:
    """Divide frases muito longas (comum em legendas sem pontuação) na melhor pausa/vírgula."""
    if not words:
        return []
    if words[-1]["end"] - words[0]["start"] <= max_s or len(words) < 4:
        return [Sentence(words[0]["start"], words[-1]["end"], list(words))]
    best_i, best_val = len(words) // 2, -1.0
    for i in range(1, len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        comma = 0.3 if words[i]["text"].endswith((",", ";", ":")) else 0.0
        balance = 1 - abs(i - len(words) / 2) / len(words)
        val = gap + comma + 0.2 * balance
        if val > best_val:
            best_i, best_val = i, val
    return _split_long(words[: best_i + 1], max_s) + _split_long(words[best_i + 1:], max_s)


def generate_candidates(sentences: list[Sentence], min_s: float, max_s: float,
                        lead_in: float = 0.15, tail: float = 0.35) -> list[Candidate]:
    cands: list[Candidate] = []
    n = len(sentences)
    for i in range(n):
        dur_found = 0
        for j in range(i, n):
            start = max(sentences[i].start - min(lead_in, sentences[i].gap_before / 2), 0)
            end = sentences[j].end + min(tail, sentences[j].gap_after / 2)
            dur = end - start
            if dur > max_s:
                break
            if dur >= min_s:
                cands.append(Candidate(start, end, sentences[i: j + 1]))
                dur_found += 1
                if dur_found >= 4:
                    break
    return cands


def _rate(x: float, lo: float, hi: float, soft: float) -> float:
    if lo <= x <= hi:
        return 1.0
    d = lo - x if x < lo else x - hi
    return max(0.0, 1 - d / soft)


def score_candidate(c: Candidate, profile: dict | None, target: tuple[float, float]) -> Candidate:
    words = c.words
    text = c.text
    ntext = norm(text)
    first = c.sentences[0]
    last = c.sentences[-1]
    reasons: list[str] = []

    # Clareza: confiança da transcrição + ritmo de fala natural
    probs = [w["prob"] for w in words if w.get("prob") is not None]
    prob_score = min(1.0, max(0.0, (sum(probs) / len(probs) - 0.5) / 0.45)) if probs else 0.75
    wps = len(words) / max(c.duration, 0.1)
    clareza = 0.6 * prob_score + 0.4 * _rate(wps, 1.8, 4.2, 1.5)

    # Independência de contexto
    first_tok = clean_token(first.words[0]["text"]) if first.words else ""
    independencia = 1.0
    if first_tok in DEPENDENT_STARTERS or any(norm(first.text).startswith(ph + " ") for ph in DEPENDENT_PHRASES):
        independencia -= 0.45
        reasons.append(f"começa com “{first.words[0]['text']}”, pode depender do contexto anterior")
    if any(norm(r) in ntext for r in CONTEXT_REFERENCES):
        independencia -= 0.35
        reasons.append("faz referência a algo dito antes")
    n_first = norm(first.text)
    if first.is_question or any(n_first.startswith(norm(h)) for h in HOOK_STARTERS):
        independencia = min(1.0, independencia + 0.15)
    independencia = max(0.0, independencia)

    # Interesse narrativo (marcadores de história, opinião, explicação, emoção...)
    cat_hits: dict[str, int] = {}
    for cat, markers in MARKERS.items():
        if cat == "Pergunta e resposta":
            hits = 2 if _asks_and_answers(c) else 0   # estrutura mais marcante que palavras soltas
        else:
            hits = sum(ntext.count(norm(m)) for m in markers)
        if hits:
            cat_hits[cat] = hits
    weighted = sum(min(h, 3) for h in cat_hits.values())
    interesse = min(1.0, 0.35 + 0.13 * weighted)
    if re.search(r"\d", text):
        interesse = min(1.0, interesse + 0.05)
    category = max(cat_hits, key=lambda k: cat_hits[k]) if cat_hits else "Fala relevante"

    # Potencial de retenção: gancho nos primeiros segundos + densidade de fala
    hook_words = [w for w in words if w["start"] - c.start <= 4.0]
    hook_text = norm(" ".join(w["text"] for w in hook_words))
    hook = 0.4
    if first.is_question or "?" in hook_text:
        hook += 0.3
    if any(hook_text.startswith(norm(h)) or f" {norm(h)} " in f" {hook_text} " for h in HOOK_STARTERS):
        hook += 0.2
    if re.search(r"\d", hook_text) or any(norm(m) in hook_text for m in MARKERS["Frase de impacto"]):
        hook += 0.1
    speech = sum(w["end"] - w["start"] for w in words)
    density = min(1.0, speech / max(c.duration, 0.1) / 0.8)
    retencao = min(1.0, 0.6 * min(hook, 1.0) + 0.4 * density)

    # Qualidade do áudio
    audio_q = audio_mod.segment_quality(profile, c.start, c.end) if profile else 0.7

    # Coerência: termina com frase completa, sem palavra de ligação pendente
    coerencia = 1.0 if last.complete else 0.45
    last_tok = clean_token(last.words[-1]["text"])
    if last_tok in DEPENDENT_ENDINGS:
        coerencia -= 0.3
    if last.is_question and len(c.sentences) > 1:
        coerencia -= 0.25  # termina perguntando, sem resposta
        reasons.append("termina com uma pergunta sem resposta")
    coerencia = max(0.0, coerencia)

    # Cortes suaves: pausa antes do início e depois do fim
    cortes = 0.5 * min(1.0, first.gap_before / 0.5) + 0.5 * min(1.0, last.gap_after / 0.5)
    if cortes < 0.4:
        reasons.append("início/fim com pouca pausa (fala contínua)")

    scores = {
        "clareza": clareza, "independencia": independencia, "interesse": interesse,
        "retencao": retencao, "audio": audio_q, "coerencia": coerencia, "cortes_suaves": cortes,
    }
    total = sum(WEIGHTS[k] * v for k, v in scores.items())
    mid = (target[0] + target[1]) / 2
    fit = _rate(c.duration, mid - (mid - target[0]) * 0.6, mid + (target[1] - mid) * 0.6, mid)
    total = total * (0.94 + 0.06 * fit)

    positives = [LABELS[k].lower() for k, v in sorted(scores.items(), key=lambda kv: -kv[1]) if v >= 0.8][:3]
    if positives:
        reasons.insert(0, "Pontos fortes: " + ", ".join(positives))
    if cat_hits:
        reasons.insert(1 if positives else 0, f"Tipo de trecho: {category.lower()}")

    # sem arredondar: notas arredondadas empatavam às dezenas e o desempate virava a ordem do tempo
    c.scores, c.score, c.category, c.reasons = scores, total * SCORE_SCALE, category, reasons
    return c


SCORE_SCALE = 96.0     # nota base vai até 96; o bônus de estilo (+4) completa 100 sem estourar o teto
STYLE_BONUS = 4.0
QA_MIN_ANSWER_S = 8.0


def _asks_and_answers(c: Candidate) -> bool:
    """Pergunta de verdade: pergunta curta na 1ª metade do corte seguida de resposta (≥ 8 s ou 40% do corte).

    Antes, qualquer "?" no meio da conversa contava, e 58% dos candidatos viravam "Pergunta e resposta".
    """
    questions = [i for i, s in enumerate(c.sentences[:-1]) if s.is_question]
    if not questions or len(questions) > 3 or c.sentences[-1].is_question:
        return False
    i = questions[0]
    q = c.sentences[i]
    if len(q.words) > 25 or q.start - c.start > 0.5 * c.duration:
        return False
    answer = [s for s in c.sentences[i + 1:] if not s.is_question]
    return sum(s.end - s.start for s in answer) >= min(QA_MIN_ANSWER_S, 0.4 * c.duration)


def _overlap(a: Candidate | dict, b: Candidate | dict) -> float:
    sa, ea = (a.start, a.end) if isinstance(a, Candidate) else (a["start"], a["end"])
    sb, eb = (b.start, b.end) if isinstance(b, Candidate) else (b["start"], b["end"])
    return max(0.0, min(ea, eb) - max(sa, sb))


COVERAGE_WINDOW_S = 20 * 60   # cortes espalhados: limite de cortes por trecho de 20 min do episódio


def _rank_key(c: Candidate) -> tuple:
    # empate exato: decide o interesse e a retenção, nunca a posição no vídeo
    return (-c.score, -c.scores.get("interesse", 0), -c.scores.get("retencao", 0), -c.duration)


def select(cands: list[Candidate], count: int, min_gap: float = 1.0,
           total_s: float | None = None) -> tuple[list[Candidate], list[Candidate]]:
    """Escolhe `count` cortes sem sobreposição + até 30 alternativas também sem sobreposição entre si.

    Em episódios longos, no máximo `per_window` cortes por trecho de 20 min na 1ª passada (os melhores de cada
    parte do episódio); se faltar corte, a 2ª passada completa sem esse limite.
    """
    ranked = sorted(cands, key=_rank_key)
    total_s = total_s if total_s is not None else max((c.end for c in cands), default=0.0)
    per_window = max(1, math.ceil(count * COVERAGE_WINDOW_S / total_s)) if total_s > COVERAGE_WINDOW_S else count
    chosen: list[Candidate] = []
    used: dict[int, int] = {}
    blocks_used: set[int] = set()
    for limited in (True, False):
        for c in ranked:
            if len(chosen) >= count:
                break
            if c in chosen:
                continue
            win = int(c.start // COVERAGE_WINDOW_S)
            # 1ª passada: um corte por bloco (assunto) e poucos por trecho de 20 min
            if limited and (used.get(win, 0) >= per_window or (c.block is not None and c.block in blocks_used)):
                continue
            if all(c.end + min_gap <= o.start or c.start >= o.end + min_gap for o in chosen):
                chosen.append(c)
                used[win] = used.get(win, 0) + 1
                if c.block is not None:
                    blocks_used.add(c.block)
    alternatives: list[Candidate] = []
    for c in ranked:
        if len(alternatives) >= 30:
            break
        if c in chosen:
            continue
        if any(_overlap(c, o) > 0.5 * c.duration for o in chosen + alternatives):
            continue
        alternatives.append(c)
    chosen.sort(key=lambda c: c.start)
    return chosen, alternatives


# Estilo do projeto → tipos de trecho priorizados (pequeno bônus na pontuação)
STYLE_PREFERENCES = {
    "podcast_premium": {"História", "Opinião", "Pergunta e resposta"},
    "entrevista": {"Pergunta e resposta", "Opinião", "História"},
    "motivacional": {"Emocionante", "Frase de impacto", "História"},
    "educativo": {"Educativo", "Curiosidade"},
    "dinamico": {"Curiosidade", "Frase de impacto", "Pergunta e resposta"},
}


BLOCK_WEIGHT = 0.55       # peso da nota do bloco (história inteira) contra a nota local da janela
BLOCK_START_BONUS = 5.0   # corte que começa onde o assunto começa se entende sozinho
CROSS_PENALTY = 12.0      # corte que atravessa dois assuntos


def _percentile_map(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = 100.0 * rank / max(len(values) - 1, 1)
    return out


def apply_blocks(cands: list[Candidate], blocks: list) -> None:
    """Combina a nota local de cada janela com a nota do bloco (assunto/história) em que ela está."""
    if not blocks or not cands:
        return
    starts = [b.start for b in blocks]
    import bisect

    local = _percentile_map([c.score for c in cands])
    for c, pct in zip(cands, local):
        i = max(0, bisect.bisect_right(starts, c.start + 0.5) - 1)
        b = blocks[i]
        inside = max(0.0, min(c.end, b.end) - max(c.start, b.start)) / max(c.duration, 0.1)
        if inside < 0.85 and i + 1 < len(blocks):
            nb = blocks[i + 1]
            if max(0.0, min(c.end, nb.end) - max(c.start, nb.start)) / max(c.duration, 0.1) > inside:
                b, inside = nb, 1 - inside
        c.block = b.index
        c.scores["historia"] = b.score / 100
        # até 95 pela combinação + 5 de bônus: só chega a 100 sem teto, então não volta a empatar
        score = 0.95 * ((1 - BLOCK_WEIGHT) * pct + BLOCK_WEIGHT * b.score)
        if abs(c.start - b.start) <= 2.5:
            score += BLOCK_START_BONUS
            c.reasons.append("começa onde o assunto começa")
        if inside < 0.85:
            score -= CROSS_PENALTY
            c.reasons.append("passa de um assunto para outro")
        if b.kind in ("Propaganda/chamada", "Abertura/encerramento"):
            score -= 40
        label = b.title or b.kind
        c.reasons.insert(0, f"Bloco: {label} (nota do bloco {round(b.score)})")
        c.score = max(0.0, score)


def find_clips(transcript: dict, count: int, min_s: float, max_s: float,
               profile: dict | None = None, style: str = "podcast_premium",
               blocks: list | None = None) -> tuple[list[Candidate], list[Candidate]]:
    words = [w for seg in transcript["segments"] for w in seg["words"]]
    if not words:
        return [], []
    sentences = build_sentences(words, max_sentence_s=max(8.0, max_s * 0.6))
    cands = generate_candidates(sentences, min_s, max_s)
    if not cands:
        # material curto ou sem pausas: relaxa o mínimo para não falhar
        cands = generate_candidates(sentences, min(min_s, 5.0), max_s)
    preferred = STYLE_PREFERENCES.get(style, set())
    for c in cands:
        score_candidate(c, profile, (min_s, max_s))
        if c.category in preferred:
            c.score += STYLE_BONUS
    if blocks is None:
        from . import episode

        blocks = episode.build(transcript, profile)
    apply_blocks(cands, blocks)
    return select(cands, count, total_s=words[-1]["end"])
