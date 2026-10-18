"""Utilidades de texto em português (normalização, stopwords, palavras-chave)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

STOPWORDS = set("""
a à ao aos aquela aquelas aquele aqueles aquilo as às até com como da das de dela delas dele deles
depois do dos e é ela elas ele eles em entre era eram essa essas esse esses esta está estão estas
estava este estes eu foi fomos for foram há isso isto já lhe lhes mais mas me mesmo meu meus minha
minhas muito na nas nem no nos nós nossa nossas nosso nossos num numa o os ou para pela pelas pelo
pelos por qual quando que quem se sem ser seu seus só sua suas também te tem têm tinha tu tua tuas
um uma umas uns você vocês vos né aí daí então tipo assim coisa coisas gente cara tá tô vai vou
ter fazer faz fez sei sabe acho bem bom boa ainda lá aqui agora sim não pra pro pras pros ia
estou estamos sou somos era foi seja sejam vamos vão dizer disse falar falou fala tudo todo toda
todos todas nada algo alguém cada outro outra outros outras onde porque pois porém sobre sob após
""".split())

DEPENDENT_STARTERS = {
    "e", "mas", "então", "entao", "aí", "ai", "daí", "dai", "porque", "pois", "isso", "isto", "essa",
    "esse", "ele", "ela", "eles", "elas", "também", "tambem", "ou", "né", "ne", "tipo", "que", "mesmo",
    "assim", "depois", "nisso", "dele", "dela", "lá", "la", "inclusive", "senão", "senao", "logo",
    "portanto", "contudo", "entretanto", "aliás", "alias", "só", "so",
}
DEPENDENT_PHRASES = ["por isso", "so que", "alem disso", "por causa disso", "nesse caso", "e ai", "com isso",
                     "dessa forma", "desse jeito", "nesse sentido", "foi ai", "foi por isso"]
DEPENDENT_ENDINGS = {"e", "mas", "que", "porque", "então", "de", "do", "da", "o", "a", "um", "uma",
                     "com", "para", "pra", "no", "na", "em", "se", "ou", "tipo", "aí"}

CONTEXT_REFERENCES = [
    "como eu falei", "como eu disse", "como você falou", "como você disse", "isso que você falou",
    "que nem eu falei", "voltando ao", "voltando no", "como falamos", "aquilo que", "o que eu tinha falado",
]

MARKERS: dict[str, list[str]] = {
    "História": ["quando eu", "um dia", "lembro", "me lembro", "aconteceu", "história", "uma vez",
                 "na época", "naquele dia", "eu tinha", "anos atrás", "certa vez", "quando era"],
    "Pergunta e resposta": ["?"],
    "Opinião": ["eu acho", "na minha opinião", "acredito", "eu penso", "pra mim", "para mim",
                "eu defendo", "discordo", "concordo", "o problema é", "a verdade é"],
    "Educativo": ["o segredo", "a diferença", "significa", "funciona", "o motivo", "por isso",
                  "o primeiro passo", "a regra", "dica", "aprendi", "o que acontece é", "ou seja",
                  "por exemplo", "o jeito", "como fazer", "estratégia", "método"],
    "Emocionante": ["chorei", "emocion", "mudou minha vida", "nunca vou esquecer", "medo", "sonho",
                    "orgulho", "perdi", "superar", "difícil", "dor", "felicidade", "coragem"],
    "Curiosidade": ["você sabia", "curioso", "curiosidade", "pouca gente sabe", "ninguém sabe",
                    "incrível", "impressionante", "surpreendente", "na verdade", "descobri"],
    "Frase de impacto": ["nunca", "sempre", "ninguém", "todo mundo", "o maior", "o pior", "o melhor",
                         "a única", "o único", "jamais", "simplesmente", "de verdade", "precisa"],
}

HOOK_STARTERS = ["você", "voce", "o segredo", "a verdade", "ninguém", "nunca", "sabe por que",
                 "o maior", "o erro", "o problema", "imagina", "se você", "por que", "o que",
                 "como", "qual"]


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def clean_token(tok: str) -> str:
    return re.sub(r"^[^\wÀ-ÿ]+|[^\wÀ-ÿ]+$", "", tok.lower())


# palavras comuns demais para virar tema/hashtag
WEAK_KEYWORDS = set("""
maior menor melhor pior muito muita muitos muitas grande grandes pequeno coisa vez vezes hoje ontem
amanhã sempre nunca tempo anos dia dias pessoa pessoas verdade mano parada negócio jeito forma momento
lado parte certo certa mesma mesmos própria próprio aquilo aqueles depois antes ainda enquanto então
porque quando onde tudo nada cada outro outra outros outras sério pouco pouca mais menos bastante
""".split())


def keywords(text: str, top: int = 8) -> list[str]:
    toks = [clean_token(t) for t in re.split(r"\s+", text)]
    toks = [t for t in toks if len(t) > 3 and t not in STOPWORDS and t not in WEAK_KEYWORDS and not t.isdigit()]
    counts = Counter(toks)
    # bônus para palavras mais longas (tendem a ser mais informativas)
    ranked = sorted(counts.items(), key=lambda kv: (kv[1] * (1 + min(len(kv[0]), 12) / 12)), reverse=True)
    return [k for k, _ in ranked[:top]]


def hashtag(word: str) -> str:
    t = norm(word)
    t = re.sub(r"[^a-z0-9]", "", t)
    return f"#{t}" if t else ""


def sentence_case(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def truncate_words(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"
