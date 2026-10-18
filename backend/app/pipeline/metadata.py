"""Sugestões de título, descrição, hashtags e palavras-chave para cada corte.

O motor heurístico só usa frases e palavras que existem na transcrição do corte,
então não inventa declarações. Com o Ollama ativado, as sugestões da IA local são
validadas (tamanho, citações precisam existir no texto) e combinadas às heurísticas.
"""
from __future__ import annotations

import re

from . import llm, phrases
from .textutil import hashtag, keywords, norm, sentence_case, truncate_words

MAX_TITLE = 70


_SHOW_RE = re.compile(r"(#\s*\d+|\bep(is[oó]dio)?\.?\s*\d+|\bpodcast\b|\bpodpah\b|\bflow\b|\bcast\b)", re.I)


_NAME_CONNECTORS = {"de", "da", "do", "dos", "das", "e"}


def _looks_like_name(part: str) -> bool:
    words = part.split()
    if not 1 <= len(words) <= 4 or len(part) > 40 or _SHOW_RE.search(part):
        return False
    if part.isupper():
        return True
    return all(w[:1].isupper() or w.lower() in _NAME_CONNECTORS for w in words)


def parse_source(source_title: str) -> tuple[str | None, str | None]:
    """Separa convidado e programa de títulos como 'CRAQUE NETO - Podpah #1093'.

    O convidado só é aceito se parecer um nome (palavras com inicial maiúscula); um título como
    'Como sair das dívidas | Primo Rico' não vira "convidado: Como sair das dívidas".
    """
    if not source_title:
        return None, None
    parts = [p.strip() for p in re.split(r"\s+[-–|:]\s+", source_title) if p.strip()]
    if len(parts) < 2:
        return None, (source_title if _SHOW_RE.search(source_title) else None)
    show = next((p for p in parts if _SHOW_RE.search(p)), None)
    guest = next((p for p in parts if p is not show and _looks_like_name(p)), None)
    if guest and guest.isupper():
        guest = guest.title()
    show_name = None
    if show:
        show_name = re.sub(r"\s*(#\s*\d+|ep(is[oó]dio)?\.?\s*\d+)\s*$", "", show, flags=re.I).strip() or show
    return guest, show_name


# gancho (1ª linha): específico do trecho, sem afirmar nada que não esteja na fala
_HOOKS = {
    "História": ["📖 {quem} contou como foi {tema_de}", "😳 A história {de_quem} {tema_sobre} é de outro nível"],
    "Opinião": ["🔥 {quem} deu a opinião sincera {tema_sobre}", "🗣️ {quem} não aliviou {tema_sobre}"],
    "Pergunta e resposta": ["🎯 A resposta {de_quem} {tema_sobre} foi direta", "🎯 Perguntaram {tema_sobre}…"],
    "Educativo": ["💡 {quem} explicou {tema_sobre} em menos de um minuto", "📌 Anota essa {tema_sobre}"],
    "Emocionante": ["🥹 {quem} se abriu {tema_sobre}", "❤️ Que momento {de_quem} {tema_sobre}"],
    "Curiosidade": ["🤯 Você sabia disso {tema_sobre}?", "👀 Pouca gente conhece esse lado {tema_sobre}"],
    "Frase de impacto": ["⚡ {quem} resumiu tudo {tema_sobre}", "💥 Essa {de_quem} {tema_sobre} diz muito"],
}
_DEFAULT_HOOKS = ["🎙️ {quem} falando {tema_sobre}", "👀 Olha esse trecho {tema_sobre}"]
# chamada final ligada ao tipo de trecho
_CTAS = {
    "Opinião": ["Você concorda {com_quem}? Comenta 👇", "Tá certo ou tá errado? Opina aqui 👇"],
    "História": ["Já passou por algo parecido? Conta aqui 👇", "Segue pra ver a continuação de outros cortes 🔥"],
    "Pergunta e resposta": ["E você, o que responderia? 👇", "Concorda com a resposta? Comenta 👇"],
    "Educativo": ["Salva pra lembrar depois 📌", "Manda pra quem precisa ouvir isso 👀"],
    "Emocionante": ["Marca alguém que precisa ouvir isso ❤️", "Comenta o que você sentiu 👇"],
    "Curiosidade": ["Você já sabia? Comenta 👇", "Manda pra alguém que não sabia disso 👀"],
    "Frase de impacto": ["Concorda? Comenta 👇", "Salva essa frase 📌"],
}
_DEFAULT_CTAS = ["Comenta o que você achou 👇", "Segue pra ver mais cortes como esse 🔥"]


def _pick(options: list[str], seed: str, salt: int = 0) -> str:
    return options[(sum(map(ord, seed)) + salt) % len(options)]


def _fmt(template: str, guest: str | None, topic: str | None) -> str:
    quem = guest or "Ele"
    out = template.format(
        quem=quem, de_quem=f"de {guest}" if guest else "dele",
        com_quem=f"com {guest}" if guest else "com ele",
        tema_sobre=f"sobre {topic}" if topic else "", tema_de=topic or "tudo")
    return re.sub(r"\s{2,}", " ", out).replace(" …", "…").replace(" ?", "?").strip()


def heuristic(text: str, source_title: str, category: str) -> dict:
    kws = keywords(text, top=8)
    guest, show = parse_source(source_title)
    tema = phrases.topic(text, exclude=(guest, show), source_title=source_title)
    topic_words = kws[:6] + ([tema] if tema else [])
    quote = phrases.best_quote(text, topic_words, max_chars=110)
    short_quote = phrases.best_quote(text, topic_words, max_chars=70)
    question = phrases.best_question(text, max_chars=MAX_TITLE + 20)

    titles: list[str] = []
    if question:
        titles.append(truncate_words(question, MAX_TITLE))
    if short_quote:
        q = truncate_words(short_quote.rstrip("."), MAX_TITLE - 2 - (len(guest) + 2 if guest else 0))
        titles.append(f"{guest}: “{q}”" if guest else f"“{q}”")
    if tema:
        label = {
            "História": "a história completa", "Opinião": "a opinião sem filtro",
            "Educativo": "o que você precisa saber", "Curiosidade": "o que pouca gente sabe",
            "Emocionante": "um momento marcante", "Pergunta e resposta": "a resposta direta",
        }.get(category, "o trecho que resume tudo")
        who = f"{guest} sobre {tema}" if guest else sentence_case(tema)
        titles.append(truncate_words(f"{who}: {label}", MAX_TITLE))
    seen, uniq = set(), []
    for t in titles:
        if t and norm(t) not in seen:
            seen.add(norm(t))
            uniq.append(t)

    tags = ["#shorts", "#cortes"]
    for name in (guest, show):
        if name:
            tags.append(hashtag(name.replace(" ", "")))
    if tema:
        tags.append(hashtag(tema.replace(" ", "")))
    tags += [h for h in (hashtag(k) for k in kws[:6] if phrases.hashtag_ok(k)) if h and len(h) > 3]
    tags = list(dict.fromkeys(t for t in tags if t))[:8]

    # descrição construída: gancho → contexto → frase real → chamada → crédito → hashtags
    where = f"No {show}, " if show else ""
    who = guest or "ele"
    context = ""
    if question:
        hook = f"🎯 {(where + who)[:1].upper() + (where + who)[1:]} responde: “{question}”"   # pergunta → resposta
    elif short_quote and phrases.score(short_quote, topic_words) >= 2.0:
        hook = f"“{short_quote.rstrip('.')}” 😳"          # frase muito forte vira o próprio gancho
        if tema and (guest or show):
            context = f"{where}{who} fala sobre {tema}."
    else:
        hook = _fmt(_pick(_HOOKS.get(category, _DEFAULT_HOOKS), text), guest, tema)
        if show and guest:
            context = f"Trecho do {show}."
    lines = [hook]
    if context:
        lines.append(context[:1].upper() + context[1:])
    if quote and quote.rstrip(".") not in hook:
        lines.append(f"“{quote.rstrip('.')}”")
    elif quote:  # a melhor frase já virou o gancho: entra a segunda melhor, se for boa
        second = phrases.best_quote(text, topic_words, max_chars=110, min_score=1.5, exclude=(quote,))
        if second:
            lines.append(f"“{second.rstrip('.')}”")
    cta = _fmt(_pick(_CTAS.get(category, _DEFAULT_CTAS), text, salt=7), guest, tema)
    lines.append(cta)
    if source_title:
        lines.append(f"🎙️ {source_title}")
    description = "\n\n".join(lines) + "\n\n" + " ".join(tags)
    return {"titles": uniq[:3], "description": description, "hashtags": tags,
            "keywords": kws, "short_text": hook, "cta": cta,
            "card": card_parts(text, topic_words, guest, category, tema)}


_LEADS = {
    "História": "{g} relembrou:", "Opinião": "{g} deu a real:", "Pergunta e resposta": "{g} respondeu:",
    "Educativo": "{g} explica:", "Emocionante": "{g} se abriu:", "Curiosidade": "{g} revelou:",
    "Frase de impacto": "{g} mandou essa:",
}
_LEADS_NO_GUEST = {
    "História": "A história:", "Opinião": "Opinião sincera:", "Pergunta e resposta": "A resposta:",
    "Educativo": "Entenda:", "Emocionante": "Que momento:", "Curiosidade": "Você sabia?",
    "Frase de impacto": "Frase forte:",
}


def card_parts(text: str, topic_words: list[str], guest: str | None, category: str,
               tema: str | None = None) -> dict:
    """Partes do título sobreposto, sempre a partir da própria fala (limpa das muletas).

    Sem frase boa o bastante, a caixa mostra o assunto ("Fulano sobre X") em vez de uma frase solta.
    """
    lead = (_LEADS.get(category, "{g} diz:").format(g=guest) if guest
            else _LEADS_NO_GUEST.get(category, "Escuta essa:"))
    quote = phrases.best_quote(text, topic_words, max_chars=80)
    quote = quote.rstrip(".") if quote else None
    question = phrases.best_question(text, max_chars=80)
    topic_line = None
    if tema:
        topic_line = f"{guest} sobre {tema}" if guest else f"Papo sobre {tema}"
    return {"lead": lead, "quote": quote, "question": question, "guest": guest, "topic_line": topic_line,
            "headline": f"{lead} “{quote}”" if quote else (topic_line or lead)}


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
    tags = base["hashtags"]
    extra = [h if h.startswith("#") else hashtag(h) for h in (data.get("hashtags") or []) if isinstance(h, str)]
    if extra:
        # fixas (#shorts, #cortes, convidado, programa) + as da IA + as de palavras-chave
        fixed = [t for t in tags if t in ("#shorts", "#cortes")] + tags[2:4]
        tags = list(dict.fromkeys(fixed + [h for h in extra if h and len(h) > 2] + tags))[:10]
        base["hashtags"] = tags

    def ok(key: str, lo: int, hi: int) -> str | None:
        v = data.get(key)
        return v.strip() if isinstance(v, str) and lo <= len(v.strip()) <= hi and _quotes_ok(v, text) else None

    card = dict(base.get("card") or {})
    caixa = data.get("caixa") if isinstance(data.get("caixa"), dict) else {}
    frase, chamada = caixa.get("frase"), caixa.get("chamada")
    if isinstance(frase, str) and len(frase.strip()) <= 90 and phrases.in_transcript(frase, text):
        card["quote"] = phrases.clean(frase.strip().strip("“”\"")).rstrip(".")
        if isinstance(chamada, str) and 4 <= len(chamada.strip()) <= 45 and '"' not in chamada and "“" not in chamada:
            card["lead"] = chamada.strip() if chamada.strip().endswith(":") else chamada.strip() + ":"
        base["engine"] = "ollama+heuristica"
    gancho, contexto, cta = ok("gancho", 8, 100), ok("contexto", 15, 200), ok("chamada", 6, 100)
    if gancho and (contexto or cta):
        lines = [gancho] + ([contexto] if contexto else [])
        if card.get("quote") and norm(card["quote"]) not in norm(gancho + " " + (contexto or "")):
            lines.append(f"“{card['quote']}”")
        lines.append(cta or base["cta"])
        if source_title:
            lines.append(f"🎙️ {source_title}")
        base["description"] = "\n\n".join(lines) + "\n\n" + " ".join(tags)
        base["short_text"] = gancho
        base["engine"] = "ollama+heuristica"
    else:
        desc = ok("descricao", 20, 600)  # formato antigo
        if desc:
            base["description"] = desc + (f"\n\n🎙️ {source_title}" if source_title else "") + "\n\n" + " ".join(tags)
    base["card"] = card
    manchete = data.get("manchete")
    if isinstance(manchete, str) and 10 <= len(manchete.strip()) <= 110 and _quotes_ok(manchete, text):
        base["card"] = dict(base.get("card") or {}) | {"headline": manchete.strip()}
    kws = [k for k in (data.get("palavras_chave") or []) if isinstance(k, str)]
    if kws:
        base["keywords"] = list(dict.fromkeys([k.strip().lower() for k in kws] + base["keywords"]))[:10]
    if isinstance(data.get("texto_curto"), str) and data["texto_curto"].strip():
        base["short_text"] = data["texto_curto"].strip()[:200]
    return base
