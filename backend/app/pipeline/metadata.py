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


_SHOW_RE = re.compile(r"(#\s*\d+|\bep(is[oó]dio)?\.?\s*\d+|\bpodcast\b|\bpodpah\b|\bflow\b|\bcast\b)", re.I)


def parse_source(source_title: str) -> tuple[str | None, str | None]:
    """Separa convidado e programa de títulos como 'CRAQUE NETO - Podpah #1093'."""
    if not source_title:
        return None, None
    parts = [p.strip() for p in re.split(r"\s+[-–|:]\s+", source_title) if p.strip()]
    if len(parts) < 2:
        return None, (source_title if _SHOW_RE.search(source_title) else None)
    show = next((p for p in parts if _SHOW_RE.search(p)), parts[-1])
    guest = next((p for p in parts if p is not show), None)
    if guest and (len(guest) > 40 or len(guest.split()) > 5):
        guest = None  # parece frase, não nome
    if guest and guest.isupper():
        guest = guest.title()
    show_name = re.sub(r"\s*(#\s*\d+|ep(is[oó]dio)?\.?\s*\d+)\s*$", "", show, flags=re.I).strip() or show
    return guest, show_name


# ganchos por tipo de trecho; {quem} = convidado (ou "ele"), {tema} = palavra-chave principal
_HOOKS = {
    "História": ["😳 {quem} contou essa história sobre {tema}…", "📖 Essa história sobre {tema} é de outro nível",
                 "😮 Olha o que aconteceu com {quem}…"],
    "Opinião": ["🔥 {quem} deu a real sobre {tema}", "🗣️ A opinião sincera sobre {tema}",
                "💥 {quem} não segurou a língua sobre {tema}"],
    "Pergunta e resposta": ["🎯 Perguntaram sobre {tema} e a resposta foi direta", "❓ Você sabe a resposta? Olha o que {quem} disse",
                            "🎯 A pergunta foi sobre {tema}… e a resposta?"],
    "Educativo": ["💡 Presta atenção nessa explicação sobre {tema}", "🧠 Isso sobre {tema} muda a forma de pensar",
                  "📌 Salva esse: {tema} explicado em segundos"],
    "Emocionante": ["🥹 Que momento… {quem} falando sobre {tema}", "❤️ Esse trecho sobre {tema} tocou fundo",
                    "🥹 Não tem como não sentir esse momento"],
    "Curiosidade": ["🤯 Você sabia disso sobre {tema}?", "👀 Pouca gente presta atenção nisso sobre {tema}",
                    "🤯 Essa sobre {tema} eu não sabia"],
    "Frase de impacto": ["⚡ {quem} mandou essa sobre {tema}", "💣 Essa frase sobre {tema} diz tudo",
                         "⚡ Escuta até o final"],
}
_DEFAULT_HOOKS = ["🎙️ {quem} falando sobre {tema}", "👀 Olha esse trecho sobre {tema}", "🔥 Esse corte vale o play"]
_CTAS = ["Comenta aqui: você concorda? 👇", "Marca aquele amigo que precisa ver isso 👀",
         "Segue pra ver mais cortes como esse 🔥", "Salva pra assistir de novo depois 📌",
         "E você, o que faria? Comenta 👇"]


def _pick(options: list[str], seed: str, salt: int = 0) -> str:
    return options[(sum(map(ord, seed)) + salt) % len(options)]


def _best_quote(sents: list[str], kws: list[str], max_chars: int = 110) -> str | None:
    def strength(s: str) -> float:
        ns = norm(s)
        k = sum(1 for kw in kws[:5] if norm(kw) in ns)
        punch = 0.6 if s.endswith(("!", "?")) else 0.0
        size = 1.0 if 25 <= len(s) <= max_chars else 0.0
        return k + punch + size
    good = [s for s in sents if len(s) <= max_chars]
    return max(good, key=strength) if good else None


def heuristic(text: str, source_title: str, category: str) -> dict:
    sents = _sentences(text)
    kws = keywords(text, top=8)
    guest, show = parse_source(source_title)
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
        quote = truncate_words(affirm[0].rstrip("."), MAX_TITLE - 2 - (len(guest) + 2 if guest else 0))
        titles.append(f"{guest}: “{quote}”" if guest else f"“{quote}”")

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

    tags = ["#shorts", "#cortes"]
    for name in (guest, show):
        if name:
            tags.append(hashtag(name.replace(" ", "")))
    tags += [h for h in (hashtag(k) for k in kws[:4]) if h and len(h) > 3]
    tags = list(dict.fromkeys(t for t in tags if t))[:8]

    # descrição estilo TikTok: gancho + frase forte + chamada + crédito + hashtags
    tema = kws[0] if kws else "isso"
    quem = guest or "ele"
    hook = _pick(_HOOKS.get(category, _DEFAULT_HOOKS), text).format(quem=quem, tema=tema)
    if not guest and "{quem}" in _pick(_HOOKS.get(category, _DEFAULT_HOOKS), text):
        hook = _pick(_DEFAULT_HOOKS[1:], text).format(quem=quem, tema=tema)
    lines = [hook]
    quote = _best_quote(sents, kws)
    if quote:
        lines.append(f"“{quote.rstrip('.')}”")
    lines.append(_pick(_CTAS, text, salt=7))
    if source_title:
        lines.append(f"🎙️ {source_title}")
    description = "\n\n".join(lines) + "\n\n" + " ".join(tags)
    return {"titles": uniq[:3], "description": description, "hashtags": tags,
            "keywords": kws, "short_text": hook}


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
        # fixas (#shorts, #cortes, convidado, programa) + as da IA + as de palavras-chave
        fixed = [t for t in tags if t in ("#shorts", "#cortes")] + tags[2:4]
        tags = list(dict.fromkeys(fixed + [h for h in extra if h and len(h) > 2] + tags))[:10]
        base["hashtags"] = tags
        base["description"] = desc.strip() + (f"\n\n🎙️ {source_title}" if source_title else "") \
            + "\n\n" + " ".join(tags)
    tema = data.get("tema")
    if isinstance(tema, str) and 3 <= len(tema.strip()) <= 42:
        base["theme"] = tema.strip()
    kws = [k for k in (data.get("palavras_chave") or []) if isinstance(k, str)]
    if kws:
        base["keywords"] = list(dict.fromkeys([k.strip().lower() for k in kws] + base["keywords"]))[:10]
    if isinstance(data.get("texto_curto"), str) and data["texto_curto"].strip():
        base["short_text"] = data["texto_curto"].strip()[:200]
    return base
