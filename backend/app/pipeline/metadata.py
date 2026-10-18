"""Sugestões de título, descrição, hashtags e palavras-chave para cada corte.

O motor heurístico só usa frases e palavras que existem na transcrição do corte,
então não inventa declarações. Com o Ollama ativado, as sugestões da IA local são
validadas (tamanho, citações precisam existir no texto) e combinadas às heurísticas.
"""
from __future__ import annotations

import re

from . import llm
from .textutil import hashtag, keywords, norm, sentence_case, truncate_words

MAX_TITLE = 70


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 3]


def heuristic(text: str, source_title: str, category: str) -> dict:
    sents = _sentences(text)
    kws = keywords(text, top=8)
    titles: list[str] = []

    questions = [s for s in sents if s.endswith("?") and 15 <= len(s) <= MAX_TITLE + 20]
    if questions:
        titles.append(truncate_words(sentence_case(questions[0]), MAX_TITLE))

    # frase mais "forte": curta o bastante e com palavras-chave
    def strength(s: str) -> float:
        ns = norm(s)
        k = sum(1 for kw in kws[:5] if norm(kw) in ns)
        size = 1.0 if 25 <= len(s) <= MAX_TITLE else 0.5
        return k + size
    affirm = sorted([s for s in sents if not s.endswith("?")], key=strength, reverse=True)
    if affirm:
        quote = truncate_words(affirm[0].rstrip("."), MAX_TITLE - 2)
        titles.append(f"“{quote}”")

    if kws:
        topic = sentence_case(kws[0])
        label = {
            "História": "a história por trás",
            "Opinião": "uma opinião sincera",
            "Educativo": "o que você precisa saber",
            "Curiosidade": "uma curiosidade",
            "Emocionante": "um momento marcante",
            "Pergunta e resposta": "a resposta direta",
        }.get(category, "o trecho que resume tudo")
        titles.append(truncate_words(f"{topic}: {label}", MAX_TITLE))

    seen, uniq = set(), []
    for t in titles:
        if t and norm(t) not in seen:
            seen.add(norm(t))
            uniq.append(t)

    tags = ["#shorts"] + [h for h in (hashtag(k) for k in kws[:5]) if h and len(h) > 3]
    summary = " ".join(sents[:2]) if sents else text[:200]
    description = truncate_words(summary, 240)
    if source_title:
        description += f"\n\nTrecho de: {source_title}"
    description += "\n\n" + " ".join(dict.fromkeys(tags))
    short = truncate_words(sents[0], 120) if sents else ""
    return {"titles": uniq[:3], "description": description, "hashtags": list(dict.fromkeys(tags)),
            "keywords": kws, "short_text": short}


def _quotes_ok(title: str, text: str) -> bool:
    nt = norm(text)
    for q in re.findall(r"[“\"]([^”\"]{4,})[”\"]", title):
        if norm(q).strip(" .…") not in nt:
            return False
    return True


def generate(text: str, source_title: str, category: str) -> dict:
    base = heuristic(text, source_title, category)
    base["engine"] = "heuristica"
    data = llm.metadata(text, source_title) if llm.enabled() else None
    if not data:
        return base
    ai_titles = [str(t).strip() for t in (data.get("titulos") or []) if isinstance(t, str)]
    ai_titles = [t for t in ai_titles if 8 <= len(t) <= 100 and _quotes_ok(t, text)]
    if ai_titles:
        merged = ai_titles[:2] + [t for t in base["titles"] if t not in ai_titles]
        base["titles"] = merged[:3]
        base["engine"] = "ollama+heuristica"
    desc = data.get("descricao")
    if isinstance(desc, str) and 20 <= len(desc) <= 600:
        tags = base["hashtags"]
        extra = [h if h.startswith("#") else hashtag(h) for h in (data.get("hashtags") or []) if isinstance(h, str)]
        tags = list(dict.fromkeys(tags + [h for h in extra if h and len(h) > 2]))[:8]
        base["hashtags"] = tags
        base["description"] = desc.strip() + (f"\n\nTrecho de: {source_title}" if source_title else "") \
            + "\n\n" + " ".join(tags)
    kws = [k for k in (data.get("palavras_chave") or []) if isinstance(k, str)]
    if kws:
        base["keywords"] = list(dict.fromkeys([k.strip().lower() for k in kws] + base["keywords"]))[:10]
    if isinstance(data.get("texto_curto"), str) and data["texto_curto"].strip():
        base["short_text"] = data["texto_curto"].strip()[:200]
    return base
