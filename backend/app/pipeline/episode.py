"""Mapa do episódio: divide a conversa em blocos de assunto/história e dá uma nota a cada bloco inteiro.

A seleção antiga julgava janelas soltas de 30–60 s e não sabia onde uma história começa e termina. O mapa
olha o episódio inteiro primeiro (como um editor faria) e os cortes passam a nascer dentro dos melhores blocos.

1. Fronteiras entre frases ganham pontos por: pausa longa, queda de vocabulário em comum entre o antes e o
   depois (mudança de assunto) e frases que abrem história/assunto ("deixa eu te contar", "aí um dia").
2. Blocos de 40 s a 6 min. Blocos longos são divididos na melhor fronteira interna.
3. Nota do bloco (regras): narração em 1ª pessoa no passado, marcadores de emoção/opinião/impacto,
   números, pergunta com resposta longa, densidade de fala e energia da voz; propaganda e chamada para
   se inscrever derrubam a nota. A nota final é a POSIÇÃO do bloco no episódio (percentil 0–100), então
   usa a escala toda em vez de deixar tudo entre 80 e 91.
4. Com o Ollama, os melhores blocos recebem resumo, título do assunto e nota da IA (o bloco inteiro, não frases).
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from . import phrases
from .selection import Sentence, build_sentences
from .textutil import MARKERS, STOPWORDS, clean_token, keywords, norm

MIN_BLOCK_S = 40.0
MAX_BLOCK_S = 360.0
COHESION_WINDOW_S = 45.0
STRONG_BOUNDARY = 0.62

# frases que costumam abrir uma história ou um assunto novo
STORY_OPENERS = [
    "deixa eu te contar", "vou te contar", "deixa eu contar", "vou contar", "uma vez", "teve uma vez", "um dia",
    "ai um dia", "eu lembro", "me lembro", "lembro que", "sabe o que aconteceu", "aconteceu uma", "a historia",
    "essa historia", "quando eu era", "quando eu tinha", "imagina", "cara, uma vez", "voce acredita que",
]
TOPIC_OPENERS = [
    "mudando de assunto", "falando nisso", "outra coisa", "deixa eu te perguntar", "queria te perguntar",
    "me conta", "me fala", "e sobre", "agora me", "vamos falar", "voltando", "e o", "e a historia",
]
SPONSOR_RE = re.compile(
    r"\b(patrocin\w*|cupom|link na descricao|se inscrev\w+|ativa o sininho|deixa (o|seu) like|codigo de desconto|"
    r"oferecimento|seja membro|compre na|use o codigo|parceiro oficial)\b")
# abertura/encerramento do programa: cumprimentos e despedidas não rendem corte
GREETING_RE = re.compile(
    r"\b(boa noite|boa tarde|bom dia|sejam bem.vindos|seja bem.vindo|bem.vindos? ao|bem.vindo ao|mais um episodio|"
    r"comecando mais um|estamos ao vivo|tamo ao vivo|obrigad[oa] por ter vindo|obrigad[oa] pelo convite|"
    r"valeu por ter vindo|ate a proxima|ate semana que vem|tchau|um beijo pra)\b")

# verbos de narração (1ª pessoa no passado) — sinal forte de "história"
NARRATION = {
    "fui", "falei", "cheguei", "peguei", "vi", "olhei", "pensei", "aconteceu", "tava", "estava", "era", "teve",
    "lembro", "contei", "liguei", "entrei", "sai", "saí", "voltei", "disse", "perguntei", "comecei", "achei",
    "fiquei", "tive", "fiz", "virei", "parei", "ganhei", "perdi", "briguei", "chorei", "descobri", "conheci",
    "mandei", "levei", "botei", "coloquei", "respondi", "gritei", "corri", "acordei", "morava", "trabalhava",
}


@dataclass
class Block:
    index: int
    start: float
    end: float
    sentences: list[Sentence]
    score: float = 0.0                 # 0–100 (posição no episódio)
    raw: float = 0.0
    kind: str = "Conversa"
    title: str = ""
    summary: str = ""
    signals: dict = field(default_factory=dict)
    ai: dict | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    def as_dict(self) -> dict:
        return {"index": self.index, "start": round(self.start, 2), "end": round(self.end, 2),
                "duration": round(self.duration, 1), "score": round(self.score, 1), "kind": self.kind,
                "title": self.title, "summary": self.summary, "ai": self.ai,
                "signals": {k: round(v, 3) for k, v in self.signals.items()}}


# ------------------------------------------------------------------ segmentação
def _bag(sentences: list[Sentence]) -> Counter:
    c: Counter = Counter()
    for s in sentences:
        for w in s.words:
            t = norm(clean_token(w["text"]))
            if len(t) > 3 and t not in STOPWORDS:
                c[t[:6]] += 1                    # radical simples: "trabalho/trabalhava" contam juntos
    return c


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def _starts_with(sentence: Sentence, openers: list[str]) -> bool:
    t = norm(sentence.text).lstrip(" ,.")
    return any(t.startswith(o) or t.startswith("e " + o) or t.startswith("ai " + o) for o in openers)


def boundary_scores(sents: list[Sentence]) -> list[float]:
    """Nota de 0 a ~1,5 para cortar o episódio entre a frase i e a i+1."""
    n = len(sents)
    out = [0.0] * max(n - 1, 0)
    for i in range(n - 1):
        a = i
        while a > 0 and sents[i].end - sents[a - 1].start < COHESION_WINDOW_S:
            a -= 1
        b = i + 1
        while b < n - 1 and sents[b + 1].end - sents[i + 1].start < COHESION_WINDOW_S:
            b += 1
        sim = _cosine(_bag(sents[a:i + 1]), _bag(sents[i + 1:b + 1]))
        pause = min(1.0, sents[i].gap_after / 2.5)
        score = 0.45 * (1 - sim) + 0.30 * pause
        nxt = sents[i + 1]
        if _starts_with(nxt, STORY_OPENERS):
            score += 0.45
        elif _starts_with(nxt, TOPIC_OPENERS):
            score += 0.35
        if nxt.is_question and i + 2 < n and not sents[i + 2].is_question:
            score += 0.15                         # pergunta nova seguida de resposta: assunto novo
        out[i] = score
    return out


def segment(sents: list[Sentence], scores: list[float] | None = None) -> list[tuple[int, int]]:
    """Blocos como pares (primeira frase, última frase), cobrindo o episódio inteiro."""
    if not sents:
        return []
    scores = boundary_scores(sents) if scores is None else scores
    cuts: list[int] = []                         # corte depois da frase i

    def ok(i: int, lo: int, hi: int) -> bool:
        # os dois lados com pelo menos MIN_BLOCK_S
        left = sents[i].end - sents[lo].start
        right = sents[hi].end - sents[i + 1].start
        return left >= MIN_BLOCK_S and right >= MIN_BLOCK_S

    # 1) fronteiras fortes, da melhor para a pior, respeitando o tamanho mínimo
    for i in sorted(range(len(scores)), key=lambda k: -scores[k]):
        if scores[i] < STRONG_BOUNDARY:
            break
        lo = max([c + 1 for c in cuts if c < i], default=0)
        hi = min([c for c in cuts if c > i], default=len(sents) - 1)
        if ok(i, lo, hi):
            cuts.append(i)
    cuts.sort()

    # 2) blocos longos demais: divide na melhor fronteira interna
    changed = True
    while changed:
        changed = False
        bounds = [-1] + cuts + [len(sents) - 1]
        for lo_c, hi_c in zip(bounds, bounds[1:]):
            lo, hi = lo_c + 1, hi_c
            if sents[hi].end - sents[lo].start <= MAX_BLOCK_S:
                continue
            inner = [i for i in range(lo, hi) if ok(i, lo, hi)]
            if inner:
                cuts.append(max(inner, key=lambda k: scores[k]))
                cuts.sort()
                changed = True
                break
    bounds = [-1] + cuts + [len(sents) - 1]
    return [(a + 1, b) for a, b in zip(bounds, bounds[1:])]


# ------------------------------------------------------------------ nota do bloco
def _signals(b: Block, profile: dict | None, total_s: float) -> dict:
    text = norm(b.text)
    toks = [norm(clean_token(w["text"])) for s in b.sentences for w in s.words]
    n = max(len(toks), 1)
    minutes = max(b.duration / 60, 0.25)
    narration = sum(1 for t in toks if t in NARRATION) / n * 100        # por 100 palavras
    markers = {cat: sum(text.count(norm(m)) for m in ms) / minutes for cat, ms in MARKERS.items()
               if cat != "Pergunta e resposta"}
    emotion = markers.get("Emocionante", 0) + markers.get("Frase de impacto", 0) + markers.get("Opinião", 0)
    story = markers.get("História", 0) + (1.5 if _starts_with(b.sentences[0], STORY_OPENERS) else 0)
    numbers = len(re.findall(r"\d", b.text)) / minutes
    qa = 0.0
    for i, s in enumerate(b.sentences[:-1]):
        if s.is_question:
            ans = 0.0
            for t in b.sentences[i + 1:]:
                if t.is_question:
                    break
                ans += t.end - t.start
            qa = max(qa, min(1.0, ans / 30))                           # resposta de 30 s ou mais
    speech = sum(w["end"] - w["start"] for s in b.sentences for w in s.words) / max(b.duration, 1)
    sponsor = len(SPONSOR_RE.findall(text))
    greetings = len(GREETING_RE.findall(text))
    energy = 0.0
    if profile is not None:
        try:
            import numpy as np

            win = float(profile["window"])
            db = np.asarray(profile["rms_db"])
            seg = db[int(b.start / win):int(b.end / win)]
            if len(seg) > 10:
                med = float(np.median(db[db > -60])) if np.any(db > -60) else -30.0
                energy = float(np.clip((np.percentile(seg, 90) - med) / 12, -1, 1))
        except (KeyError, TypeError, ValueError):
            energy = 0.0
    edge = 1.0 if b.start < 90 or b.end > total_s - 90 else 0.0          # abertura/encerramento do programa
    near_edge = b.start < 0.12 * total_s or b.end > 0.92 * total_s
    if greetings >= 3 or (greetings >= 2 and near_edge):
        edge = 1.0
    return {"narracao": narration, "historia": story, "emocao": emotion, "numeros": numbers, "pergunta": qa,
            "fala": speech, "energia": energy, "propaganda": float(sponsor), "borda": edge,
            "cumprimentos": float(greetings)}


def _raw_score(sig: dict, duration: float) -> float:
    s = (0.30 * min(sig["narracao"] / 4.0, 1.5) + 0.20 * min(sig["historia"] / 2.0, 1.5)
         + 0.20 * min(sig["emocao"] / 3.0, 1.5) + 0.07 * min(sig["numeros"] / 4.0, 1.0)
         + 0.12 * sig["pergunta"] + 0.11 * min(sig["fala"] / 0.75, 1.0) + 0.10 * sig["energia"])
    s -= 0.35 * min(sig["propaganda"], 3) + 0.45 * sig["borda"]
    if duration < 55:
        s -= 0.15                                 # bloco curto demais raramente fecha uma história
    return s


def _kind(sig: dict) -> str:
    if sig["propaganda"] >= 2:
        return "Propaganda/chamada"
    if sig["borda"] and sig.get("cumprimentos", 0) >= 2:
        return "Abertura/encerramento"
    if sig["narracao"] >= 3.0 or sig["historia"] >= 2.0:
        return "História"
    if sig["emocao"] >= 3.0:
        return "Opinião/impacto"
    if sig["pergunta"] >= 0.8:
        return "Pergunta e resposta"
    return "Conversa"


def _percentiles(values: list[float]) -> list[float]:
    if len(values) == 1:
        return [50.0]
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for rank, i in enumerate(order):
        out[i] = 100.0 * rank / (len(values) - 1)
    return out


def _describe(b: Block, common: set[str]) -> None:
    text = b.text
    tema = phrases.topic(text, exclude=tuple(common))
    if tema and norm(tema) in common:
        tema = None
    kws = [k for k in keywords(text, top=6) if norm(k) not in common][:4]
    quote = phrases.best_quote(text, kws + ([tema] if tema else []), max_chars=110)
    b.title = (tema or ", ".join(kws[:3]) or b.kind).strip()
    b.title = b.title[:1].upper() + b.title[1:]
    b.summary = f"“{quote.rstrip('.')}”" if quote else ""


def build(transcript: dict, profile: dict | None = None, use_llm: bool = False, max_ai_blocks: int = 8,
          log=None) -> list[Block]:
    words = [w for seg in transcript.get("segments", []) for w in seg.get("words", [])]
    if not words:
        return []
    sents = build_sentences(words, max_sentence_s=25.0)
    total_s = words[-1]["end"]
    blocks = [Block(i, sents[a].start, sents[b].end, sents[a:b + 1]) for i, (a, b) in enumerate(segment(sents))]
    for b in blocks:
        b.signals = _signals(b, profile, total_s)
        b.raw = _raw_score(b.signals, b.duration)
        b.kind = _kind(b.signals)
    for b, pct in zip(blocks, _percentiles([b.raw for b in blocks])):
        b.score = pct
    # palavras que viram "assunto" em muitos blocos são nomes do apresentador/convidado, não assunto
    topics = Counter(norm(t) for t in (phrases.topic(b.text) for b in blocks) if t)
    common = {t for t, n in topics.items() if n >= max(3, 0.12 * len(blocks))}
    for b in blocks:
        _describe(b, common)
    if use_llm and max_ai_blocks > 0:
        _ai_pass(blocks, max_ai_blocks, log)
    return blocks


# ------------------------------------------------------------------ IA local (opcional)
def _ai_pass(blocks: list[Block], limit: int, log=None) -> None:
    from . import llm

    shortlist = sorted((b for b in blocks if b.kind not in ("Propaganda/chamada", "Abertura/encerramento")),
                       key=lambda b: -b.score)[:limit]
    t0 = time.monotonic()
    for b in shortlist:
        res = llm.evaluate_block(_excerpt(b.text))
        if not res:
            if log:
                log.warning("IA não avaliou o bloco %d; mantendo só as regras", b.index)
            continue
        b.ai = res
        b.score = 0.5 * b.score + 0.5 * res["nota"]
        if res.get("titulo"):
            b.title = res["titulo"]
        if res.get("resumo"):
            b.summary = res["resumo"]
    if log:
        log.info("Mapa do episódio: IA avaliou %d bloco(s) em %.0fs",
                 sum(1 for b in shortlist if b.ai), time.monotonic() - t0)


def _excerpt(text: str, head: int = 520, tail: int = 180) -> str:
    """O começo e o fim do bloco cabem no contexto de um modelo pequeno (o desfecho costuma estar no fim)."""
    w = text.split()
    if len(w) <= head + tail:
        return text
    return " ".join(w[:head]) + " […] " + " ".join(w[-tail:])


# ------------------------------------------------------------------ arquivo do mapa (transcripts/<id>/episode_map.json)
MAP_VERSION = 1


def save(path, blocks: list[Block], transcript_mtime: float, ai: bool) -> None:
    import json

    data = {"version": MAP_VERSION, "transcript_mtime": transcript_mtime, "ai": ai,
            "blocks": [b.as_dict() for b in blocks]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path, transcript_mtime: float | None = None, need_ai: bool = False) -> list[Block] | None:
    """Mapa salvo, se ainda vale para esta transcrição (e foi feito com IA quando ela é pedida)."""
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != MAP_VERSION:
        return None
    if transcript_mtime is not None and abs(float(data.get("transcript_mtime", 0)) - transcript_mtime) > 1e-3:
        return None
    if need_ai and not data.get("ai"):
        return None
    out = []
    for d in data.get("blocks", []):
        b = Block(int(d["index"]), float(d["start"]), float(d["end"]), [], score=float(d["score"]),
                  kind=d.get("kind", ""), title=d.get("title", ""), summary=d.get("summary", ""),
                  signals=d.get("signals") or {}, ai=d.get("ai"))
        out.append(b)
    return out


def block_at(blocks: list[Block] | list[dict], t: float) -> int | None:
    for b in blocks:
        start, end = (b.start, b.end) if isinstance(b, Block) else (b["start"], b["end"])
        if start - 0.5 <= t < end:
            return b.index if isinstance(b, Block) else b["index"]
    return None
