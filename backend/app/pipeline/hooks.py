"""Gancho de abertura com payoff ("cold open").

Estrutura do Short quando há gancho:
  1. gancho: uma frase forte de um momento POSTERIOR do corte toca primeiro;
  2. desenvolvimento: o vídeo volta ao começo da história;
  3. payoff: a mesma frase aparece de novo na posição original, agora com contexto;
  4. conclusão: o que vem depois dela fecha a história.

A repetição é intencional: o render nunca remove a segunda ocorrência. Este módulo só
escolhe QUAL frase (trecho literal da fala) abre o vídeo, ou decide não usar gancho.

Cada candidato recebe 7 notas de 0 a 10 (curiosidade, clareza, impacto emocional, relevância,
continuidade, fidelidade e payoff). Com o Ollama ligado, a IA avalia os mesmos candidatos
(nunca escreve texto novo) e as notas são combinadas; sem ele, vale a heurística.
"""
from __future__ import annotations

import re
import time

from . import phrases
from .textutil import MARKERS, clean_token, keywords, norm

VERSION = 1
CRITERIA = ("curiosidade", "clareza", "impacto", "relevancia", "continuidade", "fidelidade", "payoff")
LABELS = {
    "curiosidade": "Curiosidade", "clareza": "Clareza sem contexto", "impacto": "Impacto emocional",
    "relevancia": "Relevância para a história", "continuidade": "Potencial de continuidade",
    "fidelidade": "Fidelidade ao contexto", "payoff": "Payoff narrativo",
}
# curiosidade e impacto pesam mais: são o que diferencia um gancho; os demais filtram os ruins
WEIGHTS = {"curiosidade": 0.25, "clareza": 0.13, "impacto": 0.18, "relevancia": 0.10,
           "continuidade": 0.10, "fidelidade": 0.10, "payoff": 0.14}
AI_WEIGHT = 0.6            # nota final = 60% IA + 40% heurística (quando a IA responde)
MIN_TOTAL = 5.0            # abaixo disso o corte sai sem gancho
MIN_FIDELITY = 5.0         # trava: frase que muda de sentido fora do contexto nunca é usada
MIN_S, MAX_S = 1.5, 6.0    # duração do gancho (frases completas); orações ficam em até CLAUSE_MAX_S
CLAUSE_MAX_S = 5.0
MIN_CONTEXT_S = 8.0        # contexto mínimo antes do payoff (e distância mínima entre as duas ocorrências)
MAX_CONTEXT_S = 20.0
MIN_AFTER_S = 4.0          # conteúdo mínimo depois do payoff (a conclusão)
MAX_CANDIDATES = 6         # quantos vão para a IA
MAX_POSITION = 0.8         # frase que termina depois de 80% do corte costuma ser a resolução: nunca vira gancho

_OPEN_LOOP = [norm(m) for m in (
    "o problema é", "o problema e", "ninguém sabe", "ninguem sabe", "a verdade é", "o segredo", "foi aí que",
    "foi ai que", "quando eu vi", "eu nunca", "você não vai acreditar", "voce nao vai acreditar", "até que",
    "ate que", "do nada", "de repente", "eu não sabia", "eu nao sabia", "o pior", "o mais louco", "sabe o que",
    "aconteceu", "pensei que", "achei que", "ia morrer", "quase", "nunca mais", "o que ninguém", "imagina",
)]
_CONCLUSION = [norm(m) for m in (
    "por isso que", "no final", "resumindo", "foi assim que", "e foi isso", "conclusão", "então no fim",
    "e é por isso", "essa é a lição", "moral da história", "no fim das contas",
)]
_DIALOGUE_RE = re.compile(r"\b(falou|disse|perguntou|gritou|respondeu|virou pra mim|olhou pra mim)\b|:\s*\S")
_STAKES = [norm(m) for m in (
    "gelei", "preso", "prisão", "policia", "polícia", "delegado", "chorar", "chorei", "vazia", "vazio", "morreu",
    "perdi", "quebrou", "quebrado", "demitido", "falência", "falencia", "zero", "desmaiou", "sangue", "hospital",
    "acidente", "mil reais", "milhões", "milhoes", "casamento", "traição", "traicao", "briga", "processo",
)]
_PRONOUNS = {"ele", "ela", "eles", "elas"}
_PHRASE_START = {"na", "no", "nas", "nos", "em", "para", "pra", "pro", "com", "e", "mas", "que",
                 "porque", "quando", "depois", "antes", "até", "ate", "sem", "pelo", "pela", "onde", "como"}
_NUMBERS = {"vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa", "cem", "cento",
            "duzentos", "trezentos", "quatrocentos", "quinhentos", "mil", "milhões", "milhoes", "dois", "três", "tres"}
_SPEECH_VERBS = {"fala", "falou", "disse", "diz", "perguntou", "respondeu", "gritou", "assim"}
_REVERSAL = {"mas", "porém", "porem", "só", "so", "não", "nao", "entretanto", "contudo"}
_EMOTION = [norm(m) for m in MARKERS["Emocionante"]] + [
    "nunca mais", "jamais", "absurdo", "loucura", "demais", "inacreditavel", "chorei", "chorando", "raiva", "medo", "vergonha",
    "assustado", "desesperado", "apavorou", "surreal", "bizarro"]
_QUESTION_START = tuple(norm(q) for q in ("como", "por que", "porque", "qual", "quando", "onde", "quem",
                                          "o que", "quanto", "sabe"))


# ------------------------------------------------------------------ candidatos
def _trim(span: list[dict]) -> list[dict]:
    """Tira muletas do começo e do fim do trecho (o áudio do gancho começa na 1ª palavra útil)."""
    lead = {"e", "aí", "ai", "então", "entao", "né", "ne", "cara", "mano", "tipo", "assim", "olha", "pô", "po",
            "bom", "daí", "dai", "é", "eh", "ah", "hum", "mas"}
    tail = {"né", "ne", "cara", "mano", "tipo", "assim", "entendeu", "sabe", "velho", "aí", "ai"}
    s, e = 0, len(span)
    while s < e and clean_token(span[s]["text"]) in lead:
        s += 1
    while e > s and clean_token(span[e - 1]["text"]) in tail:
        e -= 1
    return span[s:e]


def _clauses(words: list[dict]) -> list[list[dict]]:
    """Divide uma frase longa em orações (vírgula, pausa ou conjunção)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = w["text"].endswith((",", ";", ":")) or (nxt and nxt["start"] - w["end"] >= 0.35) \
            or (nxt and clean_token(nxt["text"]) in {"mas", "porque", "então", "entao"})
        if brk or nxt is None:
            out.append(cur)
            cur = []
    return out


def candidates(words: list[dict]) -> list[dict]:
    """Trechos literais de 1,5–5 s: frases, orações de frases longas e duas frases curtas vizinhas."""
    from .selection import build_sentences

    sents = build_sentences(words, max_sentence_s=12.0)
    spans: list[tuple[list[dict], bool]] = []          # (palavras, termina em fim de frase?)
    for i, s in enumerate(sents):
        dur = s.end - s.start
        if dur <= MAX_S:
            spans.append((s.words, True))
            if i + 1 < len(sents) and sents[i + 1].end - s.start <= MAX_S and sents[i + 1].start - s.end <= 0.4:
                spans.append((s.words + sents[i + 1].words, True))
        else:
            # começo mais longo da frase que cabe no gancho e termina numa palavra que fecha a ideia
            from .textutil import DEPENDENT_ENDINGS

            # corta só ANTES de uma palavra que abre outra parte da frase ("…em casamento | na frente de…"),
            # nunca no meio de uma expressão ("na frente de todo | mundo") nem antes da fala ("…e fala | assim:")
            fits = [w for w in s.words if w["end"] - s.start <= MAX_S]
            for k in range(len(fits), 5, -1):
                last, nxt = fits[k - 1], s.words[k] if k < len(s.words) else None
                tok = clean_token(last["text"])
                if tok in DEPENDENT_ENDINGS | _SPEECH_VERBS or last["text"].endswith(":"):
                    continue
                if nxt is not None and clean_token(nxt["text"]) == "e" and (tok in _NUMBERS or tok.isdigit()):
                    continue                              # "vinte | e cinco": não parte número
                if nxt is None or clean_token(nxt["text"]) in _PHRASE_START or last["text"].endswith((",", ";")):
                    spans.append((fits[:k], False))
                    break
            cl = _clauses(s.words)
            for j, c in enumerate(cl):
                spans.append((c, j == len(cl) - 1))
                if j + 1 < len(cl) and cl[j + 1][-1]["end"] - c[0]["start"] <= CLAUSE_MAX_S:
                    spans.append((c + cl[j + 1], j + 1 == len(cl) - 1))
    out, seen = [], set()
    for span, sentence_end in spans:
        span = _trim(span)
        if not span or clean_token(span[-1]["text"]) in _SPEECH_VERBS or span[-1]["text"].endswith(":"):
            continue                                      # para logo antes da fala ("…e fala assim:"): incompleto
        a, b = span[0]["start"], span[-1]["end"]
        if not (MIN_S <= b - a <= MAX_S) or len(span) < 4 or (round(a, 2), round(b, 2)) in seen:
            continue
        seen.add((round(a, 2), round(b, 2)))
        text = " ".join(w["text"] for w in span)
        out.append({"start": round(a, 3), "end": round(b, 3), "text": text, "clean": phrases.clean(text),
                    "sentence_end": sentence_end})
    return out


# ------------------------------------------------------------------ heurística
def _clamp(x: float) -> float:
    return round(min(max(x, 0.0), 10.0), 2)


def _payoff(c: dict, clip_start: float, clip_end: float, words: list[dict]) -> tuple[float, dict]:
    """Avalia a 2ª ocorrência (posição original) da frase: contexto antes, distância e conclusão depois."""
    dur = clip_end - clip_start
    before = c["start"] - clip_start
    after = clip_end - c["end"]
    need = min(max(MIN_CONTEXT_S, 0.25 * dur), MAX_CONTEXT_S)
    after_text = norm(" ".join(w["text"] for w in words if w["start"] >= c["end"]))
    revelation = any(m in after_text for m in _CONCLUSION) or len(after_text.split()) >= 12
    ok = before >= need and after >= max(MIN_AFTER_S, 0.08 * dur)
    score = 10 * (0.5 * min(before / (0.4 * dur), 1) + 0.5 * min(after / 10.0, 1))
    if revelation:
        score += 1
    info = {"context_s": round(before, 2), "after_s": round(after, 2), "needed_context_s": round(need, 2),
            "ok": ok, "reason": "" if ok else
            ("pouco contexto antes da frase" if before < need else "pouca história depois da frase")}
    return _clamp(score), info


def heuristic_scores(c: dict, words: list[dict], clip_start: float, clip_end: float, topic: set[str]) -> dict:
    text = c["clean"]
    nt = norm(text)
    toks = [clean_token(t) for t in text.split() if clean_token(t)]
    dur = clip_end - clip_start
    rel_end = (c["end"] - clip_start) / dur
    conclusion = any(m in nt for m in _CONCLUSION)

    stakes = sum(1 for m in _STAKES if m in nt)
    cur = 3.5                                         # narração neutra ("eu fiz churrasco") fica abaixo de 5
    if phrases._PUNCH_RE.search(nt):
        cur += 1.5                                    # paradoxo / frase de efeito: "prefere receber menos do que nada"
    if text.endswith("?") or nt.startswith(_QUESTION_START):
        cur += 2.0
    cur += min(sum(1.5 for m in _OPEN_LOOP if m in nt), 3.0)
    if _DIALOGUE_RE.search(text):
        cur += 1.5                                    # fala reportada: "ele falou: ..." deixa a cena em aberto
    cur += min(stakes, 2) * 1.0
    if conclusion:
        cur -= 2.0

    clar = 10 * (phrases.score(text, list(topic)) + 1) / 5

    imp = 3.0 + min(sum(1.5 for m in _EMOTION if m in nt) + 1.5 * stakes, 5.0) + (1.0 if "!" in c["text"] else 0.0)

    rel = 3.0 + min(sum(2.0 for t in set(toks) if norm(t) in topic), 5.0)

    # depois de ~55% do corte a frase tende a ser a resolução da história; no último quarto, entrega o final
    cont = 10.0 - max(0.0, rel_end - 0.55) / 0.35 * 8.0 - (3.0 if conclusion else 0.0)

    fid = 9.0
    if toks and toks[0] in _PRONOUNS:
        fid -= 1.0                                    # "ele chegou...": o sentido se mantém (clareza já desconta)
    elif toks and toks[0] in phrases._DEPENDENT_FIRST:
        fid -= 4.0                                    # "isso", "aí", "também"...: fora do contexto muda de sentido
    if re.search(r"\b(isso|isto|aquilo|disso|nisso)\b", nt):
        fid -= 1.5
    if not c["sentence_end"]:
        fid -= 1.0
    nxt = [w for w in words if c["end"] <= w["start"] <= c["end"] + 0.8]
    if nxt and clean_token(nxt[0]["text"]) in _REVERSAL:
        fid -= 3.0                                    # "eu ia desistir… mas não desisti": o gancho inverteria o sentido

    pay, info = _payoff(c, clip_start, clip_end, words)
    scores = {"curiosidade": _clamp(cur), "clareza": _clamp(clar), "impacto": _clamp(imp),
              "relevancia": _clamp(rel), "continuidade": _clamp(cont), "fidelidade": _clamp(fid), "payoff": pay}
    return {"scores": scores, "payoff": info, "spoiler": conclusion or rel_end > MAX_POSITION}


def total(scores: dict) -> float:
    return round(sum(WEIGHTS[k] * scores[k] for k in CRITERIA), 2)


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


# ------------------------------------------------------------------ escolha
def analyze(words: list[dict], clip_start: float, clip_end: float, use_llm: bool = True,
            timeout: float | None = None) -> dict:
    """Gera, avalia e escolhe o gancho. Retorna um dicionário serializável (guardado em clips.hook_json).

    `chosen` é o índice em `candidates` ou None (sem gancho, com o motivo em `reason`).
    """
    t0 = time.monotonic()
    result = {"version": VERSION, "span": [round(clip_start, 3), round(clip_end, 3)], "engine": "heuristica",
              "candidates": [], "chosen": None, "choice": None, "reason": "", "elapsed_s": 0.0}
    dur = clip_end - clip_start
    if dur < 12 or len(words) < 8:
        result["reason"] = "corte curto demais para gancho com payoff"
        return result
    text = " ".join(w["text"] for w in words)
    topic = {norm(k) for k in keywords(text, top=10) if phrases.hashtag_ok(k)}
    tp = phrases.topic(text)
    if tp:
        topic |= {norm(w) for w in tp.split()}
    pool = []
    for c in candidates(words):
        h = heuristic_scores(c, words, clip_start, clip_end, topic)
        if not h["payoff"]["ok"] or h["spoiler"] or h["scores"]["fidelidade"] < MIN_FIDELITY:
            continue
        pool.append(c | {"heuristic": h["scores"], "scores": dict(h["scores"]), "payoff": h["payoff"],
                         "total": total(h["scores"]), "reason_ai": ""})
    # melhores primeiro, sem dois candidatos sobre o mesmo trecho
    pool.sort(key=lambda c: -c["total"])
    picked: list[dict] = []
    for c in pool:
        if all(not _overlaps(c, p) for p in picked):
            picked.append(c)
        if len(picked) >= MAX_CANDIDATES:
            break
    if not picked:
        result["reason"] = "nenhuma frase com payoff adequado (contexto antes e conclusão depois)"
        result["elapsed_s"] = round(time.monotonic() - t0, 3)
        return result

    if use_llm:
        from . import llm

        if llm.enabled():
            ai = llm.evaluate_hooks(text, [{"id": i, "text": c["clean"]} for i, c in enumerate(picked)], timeout)
            if ai:
                result["engine"] = "ollama+heuristica"
                for i, c in enumerate(picked):
                    if i not in ai:
                        continue
                    c["ai"] = ai[i]["scores"]
                    c["scores"] = {k: round(AI_WEIGHT * ai[i]["scores"][k] + (1 - AI_WEIGHT) * c["heuristic"][k], 2)
                                   for k in CRITERIA}
                    if ai[i].get("spoiler"):
                        c["scores"]["continuidade"] = _clamp(c["scores"]["continuidade"] - 3)
                    c["reason_ai"] = ai[i].get("motivo", "")
                    c["total"] = total(c["scores"])
            else:
                result["reason"] = "IA local indisponível; usada a heurística"
    for c in picked:
        c["usable"] = c["total"] >= MIN_TOTAL and c["scores"]["fidelidade"] >= MIN_FIDELITY
        c.pop("sentence_end", None)
    picked.sort(key=lambda c: -c["total"])
    result["candidates"] = picked
    best = next((i for i, c in enumerate(picked) if c["usable"]), None)
    result["chosen"] = best
    if best is None:
        result["reason"] = (result["reason"] + "; " if result["reason"] else "") + \
            f"nenhum candidato atingiu a nota mínima ({MIN_TOTAL:g})"
    result["elapsed_s"] = round(time.monotonic() - t0, 3)
    return result


def selected(hook: dict | None, clip_start: float, clip_end: float) -> tuple[float, float] | None:
    """Intervalo do gancho, relativo ao início do corte, respeitando a escolha manual. None = sem gancho."""
    if not hook or hook.get("span") != [round(clip_start, 3), round(clip_end, 3)]:
        return None
    choice = hook.get("choice")
    if choice == "none":
        return None
    idx = choice if isinstance(choice, int) else hook.get("chosen")
    cands = hook.get("candidates") or []
    if idx is None or not 0 <= idx < len(cands):
        return None
    c = cands[idx]
    a = max(c["start"] - clip_start - 0.05, 0.0)
    b = min(c["end"] - clip_start + 0.15, clip_end - clip_start)
    return round(a, 3), round(b, 3)


def is_current(hook: dict | None, clip_start: float, clip_end: float) -> bool:
    return bool(hook) and hook.get("version") == VERSION and hook.get("span") == [round(clip_start, 3),
                                                                                  round(clip_end, 3)]
