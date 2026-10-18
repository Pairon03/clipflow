"""Escolha de frases que fazem sentido sozinhas (para títulos, caixa de texto e descrição).

A fala transcrita vem cheia de muletas ("né", "aí", "tipo", "tá ligado") e de frases que
dependem do que veio antes ("isso aí eu falo..."). Aqui as frases são limpas e pontuadas
pela capacidade de serem entendidas fora de contexto. Nada é inventado: o texto final é
sempre a própria fala, só sem as muletas.
"""
from __future__ import annotations

import re
from collections import Counter

from .textutil import CONTEXT_REFERENCES, DEPENDENT_ENDINGS, MARKERS, STOPWORDS, WEAK_KEYWORDS, clean_token, norm

_FILLER_WORDS = r"(?:e|aí|ai|então|entao|mas|né|ne|cara|mano|véi|velho|tipo|assim|olha|pô|po|bom|enfim|daí|dai|" \
                r"tá|ta|ah|eh|é|hum|uhum|bem|pois|sabe|porque|só que|so que|e aí|e ai|tipo assim|isso aí|isso ai)"
_START_RE = re.compile(rf"^(?:{_FILLER_WORDS}[,\s]+)+", re.I)
_END_RE = re.compile(r"(?:[,\s]+(?:né|ne|entendeu|sabe|tá ligado|ta ligado|cara|mano|tipo|assim|velho|irmão|"
                     r"beleza|certo|viu))+(?=[\s.!?…]*$)", re.I)
_MID_RE = re.compile(r",\s*(?:né|tipo assim|tipo|tá ligado|ta ligado|entendeu|sabe|cara|mano)\s*,", re.I)
_REPEAT_RE = re.compile(r"\b(\w+)(?:\s+\1\b)+", re.I)
# pronome repetido logo depois do sujeito: "O Neymar ele tinha" → "O Neymar tinha"
_SUBJ_PRONOUN_RE = re.compile(r"^((?:o|a)\s+[A-ZÀ-Ý][\wÀ-ÿ]+)\s+(?:ele|ela)\s+", re.I)

_DEPENDENT_FIRST = {"ele", "ela", "eles", "elas", "isso", "isto", "esse", "essa", "esses", "essas", "aquilo",
                    "aquele", "aquela", "lá", "la", "dele", "dela", "nisso", "disso", "daquilo", "também",
                    "tambem", "depois", "aí", "ai", "foi", "senão", "inclusive"}
_FILLERS = {"né", "ne", "tipo", "cara", "mano", "assim", "aí", "ai", "daí", "tá", "ta", "entendeu", "sabe",
            "velho", "pô", "po", "hum", "eh", "ah"}
_FIRST_PERSON = {"eu", "meu", "minha", "meus", "minhas", "me", "comigo", "mim"}
_QUESTION_WORDS = ("como", "por que", "porque", "qual", "quais", "quando", "onde", "quem", "o que", "quanto",
                   "você", "voce", "vocês", "será", "sera", "tem como", "dá pra", "da pra", "e se")
_STRONG = [norm(m) for cat in ("Opinião", "Frase de impacto", "Educativo", "Emocionante", "Curiosidade")
           for m in MARKERS[cat]]
_DEICTIC_RE = re.compile(r"\b(isso|isto|aquilo|disso|nisso|daquilo)\b")
_PUNCH_RE = re.compile(r"\bsem\b.+\bnao\b|\bnao\b.+\b(nada|nunca|ninguem|jamais)\b|\bo segredo\b|\ba verdade\b|"
                       r"\be (o|a) (maior|melhor|pior|unico|unica)\b|\bvale (mais|a pena)\b")
_TAG_QUESTION_RE = re.compile(r"[,\s]+(?:tá ligado|ta ligado|entendeu|sabe|né|certo|viu)\s*\?\s*$", re.I)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) > 3]


def clean(sentence: str) -> str:
    """Tira muletas do começo/fim e do meio, repetições e o pronome redundante; ajusta a maiúscula."""
    s = sentence.strip()
    s = _TAG_QUESTION_RE.sub(".", s)          # "..., tá ligado?" é afirmação, não pergunta
    for _ in range(3):
        s = _MID_RE.sub(",", s)
    s = _REPEAT_RE.sub(r"\1", s)
    prev = None
    while prev != s:
        prev = s
        s = _START_RE.sub("", s).strip()
        s = _END_RE.sub("", s).strip()
    s = _SUBJ_PRONOUN_RE.sub(r"\1 ", s)
    s = re.sub(r"\s+([,.!?…])", r"\1", re.sub(r"\s{2,}", " ", s)).strip(" ,;:-")
    return s[:1].upper() + s[1:] if s else s


def _words(s: str) -> list[str]:
    return [clean_token(t) for t in s.split() if clean_token(t)]


def is_question(sentence: str) -> bool:
    s = clean(sentence)
    return s.endswith("?") and len(_words(s)) >= 4 and norm(s).startswith(tuple(norm(q) for q in _QUESTION_WORDS)) \
        or (s.endswith("?") and len(_words(s)) >= 6)


def score(sentence: str, topic_words: list[str]) -> float:
    """Quão bem a frase (já limpa) se sustenta sozinha e chama atenção. < 1 = fraca."""
    words = _words(sentence)
    n = len(words)
    if n < 4 or n > 24:
        return -5.0
    ns = norm(sentence)
    sc = 0.0
    sc += 1.0 if 6 <= n <= 16 else 0.3
    if words[0] in _DEPENDENT_FIRST:
        sc -= 1.6                                   # depende do que veio antes
    if any(ref in ns for ref in CONTEXT_REFERENCES):
        sc -= 2.0
    if words[-1] in DEPENDENT_ENDINGS:
        sc -= 1.5                                   # cortada no meio
    fillers = sum(1 for w in words if w in _FILLERS)
    if fillers / n > 0.12:
        sc -= 1.0
    if _DEICTIC_RE.search(ns):
        sc -= 0.8                                   # "isso", "aquilo": aponta para algo fora da frase
    if _PUNCH_RE.search(ns):
        sc += 0.5                                   # estrutura de frase de efeito
    if any(w in _FIRST_PERSON for w in words):
        sc += 0.5                                   # fala pessoal rende boa citação
    sc += min(sum(0.6 for m in _STRONG if m in ns), 1.5)
    tw = {norm(t) for t in topic_words}
    sc += min(sum(0.4 for w in set(words) if norm(w) in tw), 1.2)
    if sentence.endswith("!"):
        sc += 0.3
    if re.search(r"\d|\b(dois|três|tres|cinco|dez|cem|mil|milhões|milhoes|bilhões)\b", ns):
        sc += 0.3
    return round(sc, 3)


def candidates(text: str) -> list[str]:
    """Frases limpas + orações de frases longas (a transcrição às vezes não pontua)."""
    out: list[str] = []
    for s in sentences(text):
        c = clean(s)
        if c:
            out.append(c)
        if len(_words(c)) > 18:
            for part in re.split(r",\s+|\s+(?=mas\s|porque\s|só que\s|então\s)", c):
                p = clean(part)
                if p and p != c:
                    out.append(p if p.endswith((".", "!", "?")) else p + ".")
    return list(dict.fromkeys(out))


def best_quote(text: str, topic_words: list[str], max_chars: int = 90, min_score: float = 1.0,
               allow_questions: bool = False, exclude: tuple[str | None, ...] = ()) -> str | None:
    """A frase mais forte que se entende sozinha, ou None se nenhuma for boa o bastante."""
    skip = {_plain(e) for e in exclude if e}
    best, best_sc = None, min_score
    for c in candidates(text):
        if len(c) > max_chars or (c.endswith("?") and not allow_questions):
            continue
        if any(_plain(c) in sk or sk in _plain(c) for sk in skip):
            continue
        sc = score(c, topic_words)
        if sc > best_sc:
            best, best_sc = c, sc
    return best


def best_question(text: str, max_chars: int = 90) -> str | None:
    for s in sentences(text):
        if is_question(s):
            c = clean(s)
            if ":" in c[:-1]:                           # "A pergunta que mais recebo é essa: como...?"
                tail = clean(c.rsplit(":", 1)[1])
                if len(_words(tail)) >= 4:
                    c = tail
            if len(c) <= max_chars and _words(c)[0] not in _DEPENDENT_FIRST:
                return c
    return None


def _stem(w: str) -> str:
    w = norm(w)
    return w[:-1] if w.endswith("s") and len(w) > 4 else w


def _names(text: str, excl: set[str]) -> Counter[str]:
    """Nomes próprios (sequências de palavras com inicial maiúscula fora do início da frase)."""
    names: Counter[str] = Counter()
    for s in sentences(text):
        toks = [re.sub(r"[^\wÀ-ÿ]", "", t) for t in s.split()]
        i = 1                                          # a 1ª palavra é maiúscula por ser início de frase
        while i < len(toks):
            run = []
            while i < len(toks) and len(toks[i]) > 1 and toks[i][0].isupper():
                run.append(toks[i])
                i += 1
            run = [w for w in run if norm(w) not in STOPWORDS]
            name = " ".join(run)
            if run and len(name) > 2 and not {norm(w) for w in run} & excl:
                names[name] += 1
            i += 1
    return names


def topic(text: str, exclude: tuple[str | None, ...] = (), source_title: str = "") -> str | None:
    """Assunto do trecho: nome próprio repetido > palavra do título do vídeo que aparece na fala >
    par de palavras repetido > nome composto > palavra-chave."""
    excl = {norm(w) for e in exclude if e for w in e.split()}
    names = _names(text, excl)
    if names and names.most_common(1)[0][1] >= 2:
        return names.most_common(1)[0][0]
    toks = [clean_token(t) for t in (text or "").split()]
    spoken = {_stem(t) for t in toks}
    title_words = [clean_token(t) for t in re.split(r"[\s|\-–:#]+", source_title or "")]
    title_hits = [t for t in title_words if len(t) > 4 and t not in STOPWORDS | WEAK_KEYWORDS
                  and norm(t) not in excl and _stem(t) in spoken]
    if title_hits:
        return max(title_hits, key=len)
    pairs: Counter[str] = Counter()
    for a, b in zip(toks, toks[1:]):
        if len(a) > 3 and len(b) > 3 and not {a, b} & (STOPWORDS | WEAK_KEYWORDS) and norm(a) not in excl:
            pairs[f"{a} {b}"] += 1
    if pairs and pairs.most_common(1)[0][1] >= 2:
        return pairs.most_common(1)[0][0]
    multi = [n for n in names if " " in n]
    if multi:
        return multi[0]
    from .textutil import keywords

    kws = [k for k in keywords(text, top=5) if norm(k) not in excl and hashtag_ok(k)]
    return kws[0] if kws else None


_VERB_ENDINGS = ("ar", "er", "ir", "ou", "eu", "iu", "ava", "avam", "ando", "endo", "indo", "aram", "eram", "iram",
                 "ia", "iam", "ei", "amos", "emos", "imos")
_NOT_TOPIC = {"ninguem", "alguem", "ninguém", "alguém", "pessoal", "cinquenta", "vinte", "trinta", "quarenta",
              "sessenta", "setenta", "oitenta", "noventa", "dezessete", "dezoito", "dezenove", "primeiro", "segundo",
              "terceiro", "passo", "simples", "fácil", "facil", "difícil", "dificil", "óbvio", "obvio",
              "faço", "faco", "falo", "acho", "digo", "tenho", "quero", "posso", "vejo", "penso", "gosto", "fico",
              "conheço", "conheco", "lembro", "preciso", "consigo"}


def hashtag_ok(word: str) -> bool:
    """Palavra boa para tema/hashtag: substantivo provável (não verbo, número ou pronome)."""
    w = norm(clean_token(word))
    if len(w) <= 3 or w in _NOT_TOPIC or w in STOPWORDS or w in WEAK_KEYWORDS:
        return False
    return not w.endswith(_VERB_ENDINGS) or w.endswith(("dor", "lar", "dar", "mar")) and len(w) > 5


def _plain(text: str) -> str:
    """Texto normalizado sem pontuação e sem muletas, para comparar frases com a transcrição."""
    toks = [clean_token(t) for t in norm(text or "").split()]
    return " ".join(t for t in toks if t and t not in _FILLERS and t not in {"e", "que", "o", "a"})


def in_transcript(phrase: str, text: str) -> bool:
    """A frase (talvez sem as muletas) existe na transcrição? Usado para validar o que vem da IA."""
    p = _plain(phrase)
    return len(p.split()) >= 3 and p in _plain(text)
