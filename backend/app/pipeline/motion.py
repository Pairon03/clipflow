"""Motion graphics (opcional): trechos do corte viram uma explicação animada sobre fundo claro.

Durante um bloco, o vídeo do podcast dá lugar a cenas desenhadas (título, destaque, ícone, número grande,
cartões, gráfico de comparação). A fala e a legenda continuam por cima: a animação só ILUSTRA o que é dito,
e todo texto na tela sai de palavras da própria fala (o ícone é a única coisa escolhida).

Roteiro: blocos curtos (4–8 s) nos trechos mais "visuais" (números, nomes, comparações), no máximo um a cada
~20 s, com pelo menos 4 s de podcast entre eles. Modos: "auto", "inicio" (o primeiro bloco abre o corte).
Com o Ollama ligado, a IA refina cada cena; textos que não estão na fala são descartados.

Os quadros são desenhados com Pillow (sem navegador) e gravados como vídeo com transparência (qtrle).
"""
from __future__ import annotations

import math
import re
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import config
from .textutil import STOPWORDS, norm

ICON_DIR = config.ASSETS_DIR / "icons"
FPS = 30
REVEAL_S = 0.35
MIN_BLOCK_S, MAX_BLOCK_S = 3.5, 10.0
MIN_GAP_S = 4.0
KINDS = ("destaque", "numero", "cartoes", "comparacao")
MODES = ("nenhum", "auto", "inicio")

THEME = {
    "bg": (238, 242, 247), "dot": (201, 211, 227), "navy": (20, 33, 61), "sub": (106, 120, 148),
    "blue": (47, 107, 255), "blue_dark": (30, 79, 209), "coral": (255, 77, 90), "coral_dark": (217, 55, 67),
    "soft": (234, 240, 255), "gray": (184, 195, 214), "gold": (242, 169, 0), "white": (255, 255, 255),
}

# palavra (sem acento, minúscula, começo da palavra) → ícone
ICON_WORDS = [
    (("dinheiro", "reais", "real ", "grana", "salario", "pagar", "pagou", "pago", "milhao", "milhoes", "mil "), "banknote"),
    (("rico", "fortuna", "lucro"), "dollar-sign"),
    (("campeao", "campeoes", "titulo", "taca", "copa", "libertadores", "brasileirao", "champions"), "trophy"),
    (("gol", "futebol", "bola", "campo", "jogo", "jogar", "jogador", "time ", "selecao", "clube"), "goal"),
    (("ganhou", "venceu", "vitoria", "medalha", "premio"), "medal"),
    (("carro", "dirigir", "dirigindo", "moto", "estrada"), "car"),
    (("casa", "apartamento", "morar", "morava"), "house"),
    (("aviao", "viagem", "viajar", "aeroporto"), "plane"),
    (("familia", "pai ", "mae ", "filho", "filha", "irmao", "irma", "parente"), "users"),
    (("amor", "namorada", "namorado", "casamento", "casar", "esposa", "marido", "paixao"), "heart"),
    (("traicao", "traiu", "corno", "separou", "separacao", "termin"), "heart-crack"),
    (("policia", "policial", "viatura"), "siren"),
    (("preso", "prisao", "cadeia"), "lock"),
    (("justica", "processo", "juiz", "advogado", "tribunal"), "gavel"),
    (("medico", "hospital", "doente", "cirurgia"), "hospital"),
    (("remedio", "droga"), "pill"),
    (("academia", "treino", "treinar", "musculacao"), "dumbbell"),
    (("comida", "comer", "comendo", "restaurante", "almoco", "janta"), "utensils"),
    (("cafe",), "coffee"),
    (("cerveja", "bebida", "beber", "bebado", "bebe ", "balada"), "beer"),
    (("vinho",), "wine"),
    (("bebe ", "nenem", "gravida"), "baby"),
    (("cachorro", "cao "), "dog"),
    (("gato",), "cat"),
    (("musica", "cantar", "cantor", "show"), "music"),
    (("celular", "whatsapp", "mensagem", "ligou", "ligacao"), "smartphone"),
    (("televisao", "tv ", "novela", "programa"), "tv"),
    (("video", "filme", "youtube", "canal"), "film"),
    (("podcast", "entrevista", "microfone"), "mic"),
    (("escola", "faculdade", "estudar", "estudo", "professor"), "graduation-cap"),
    (("livro", "ler "), "book-open"),
    (("trabalho", "emprego", "empresa", "negocio", "chefe"), "briefcase"),
    (("igreja", "deus", "fe "), "church"),
    (("morte", "morreu", "morrer", "matou"), "skull"),
    (("medo", "perigo", "risco"), "triangle-alert"),
    (("ideia", "pensei", "descobri"), "lightbulb"),
    (("meta", "objetivo", "foco"), "target"),
    (("sucesso", "cresceu", "crescer", "explodiu"), "rocket"),
    (("famoso", "fama", "estrela"), "star"),
    (("rei ", "melhor do mundo"), "crown"),
    (("tempo", "hora", "minuto"), "clock"),
    (("ano", "dia ", "mes ", "semana", "idade"), "calendar"),
    (("mundo", "pais", "brasil", "europa", "exterior"), "globe"),
    (("cidade", "bairro", "lugar"), "map-pin"),
    (("festa", "comemor"), "party-popper"),
    (("presente",), "gift"),
    (("comprar", "comprou", "loja"), "shopping-cart"),
    (("game", "videogame"), "gamepad-2"),
    (("amigo", "amizade", "parceiro", "parceria"), "handshake"),
    (("cabeca", "pensar", "mente", "psicolog"), "brain"),
    (("subiu", "aumentou", "dobrou"), "trending-up"),
    (("caiu", "perdeu", "piorou", "diminuiu", "parou", "eliminad"), "trending-down"),
    (("dormir", "sono", "dormia"), "bed"),
    (("ingresso",), "ticket"),
    (("fogo", "incendio", "quente"), "flame"),
]
DEFAULT_ICON = "message-circle"

FILLERS = {"ne", "tipo", "cara", "mano", "entao", "ai", "assim", "olha", "po", "bom", "enfim", "dai", "tipo,",
           "sei", "la", "velho", "irmao", "tá", "ta", "uai", "ok", "hein", "e"}
BREAK_WORDS = {"que", "com", "e", "mas", "porque", "pra", "para", "na", "no", "em", "se", "quando", "ai"}
LEAD_STOP = {"e", "mas", "que", "entao", "ai", "porque", "tipo", "ne", "cara", "mano", "so", "assim", "a", "o", "foi",
             "quando", "esquece", "ta", "nao", "ja", "um", "uma", "de", "do", "da"}
NUM_WORDS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
             "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quinze": 15, "vinte": 20,
             "trinta": 30, "quarenta": 40, "cinquenta": 50, "cem": 100, "cento": 100, "mil": 1000}
COMPARE = ("antes", "depois", "mais que", "menos que", "maior", "menor", "subiu", "caiu", "dobrou", "perdeu",
           "ganhou", "passou de", "virou")
COMMON_WORDS = {"depois", "antes", "agora", "hoje", "ontem", "amanha", "sempre", "nunca", "ainda", "tambem", "aqui",
                "ali", "la", "sim", "nao", "obrigado", "olha", "gente", "verdade", "claro", "tipo", "esquece",
                "quando", "porque", "foi", "era", "tem", "vai", "fez", "nem", "muito", "cara", "mano", "nos"}
NOT_NAMES = {"eu", "ele", "ela", "nós", "nos", "você", "voce", "a", "o", "e", "é", "então", "mas", "tipo", "cara",
             "não", "nao", "sim", "deus", "tá", "ta", "aí", "ai", "isso", "esse", "essa", "porque", "quando"}


# ================================================================ roteiro
def _clean(tok: str) -> str:
    return re.sub(r"[^\wÀ-ÿ%-]", "", tok)


def _n(tok: str) -> str:
    return norm(_clean(tok))


def sentences(words: list[dict]) -> list[list[dict]]:
    """Orações: cortes em pontuação (inclusive vírgula) ou pausa; orações curtíssimas vão junto da anterior."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if re.search(r"[.,;:!?…]$", w["text"].strip()) or (nxt and nxt["start"] - w["end"] >= 0.35) or nxt is None:
            out.append(cur)
            cur = []
    merged: list[list[dict]] = []
    for s in out:
        if merged and s[-1]["end"] - s[0]["start"] < 0.6:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return merged


def _number(words: list[dict]) -> tuple[int, str] | None:
    """Índice e texto (dígitos) do primeiro número da fala."""
    for i, w in enumerate(words):
        t = _clean(w["text"])
        if re.fullmatch(r"\d+([.,]\d+)?%?", t) and t not in ("0",):
            return i, t
        n = _n(w["text"])
        if n in NUM_WORDS and n not in ("um", "uma"):
            return i, str(NUM_WORDS[n])
    return None


_LOCAL = threading.local()   # .common: nomes repetidos no corte inteiro (o assunto), definidos em plan() por thread


def _names(words: list[dict]) -> list[tuple[str, float]]:
    out, seen = [], set()
    for i, w in enumerate(words):
        t = _clean(w["text"])
        prev = words[i - 1]["text"].strip() if i else "."
        sentence_start = bool(re.search(r"[.!?]$", prev)) and not prev.endswith("...")
        if (len(t) > 2 and t[:1].isupper() and not t.isupper() and t.lower() not in NOT_NAMES
                and t.lower() not in getattr(_LOCAL, "common", ()) and norm(t) not in STOPWORDS and norm(t) not in COMMON_WORDS
                and not sentence_start and i > 0):
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append((t, w["start"]))
    return out


def _icon_for(text: str) -> str:
    t = f" {norm(text)} "
    for keys, icon in ICON_WORDS:
        if any(f" {k}" in t if k.endswith(" ") else f" {k}" in t for k in keys):
            return icon
    return DEFAULT_ICON


def _content(words: list[dict]) -> list[dict]:
    ws = [w for w in words if _n(w["text"]) not in FILLERS and _clean(w["text"])]
    while ws and _n(ws[0]["text"]) in LEAD_STOP:
        ws = ws[1:]
    return ws


def _phrase(ws: list[dict], max_words: int, max_chars: int, min_words: int = 1) -> str:
    out: list[str] = []
    ws = [w for w in ws if _clean(w["text"])]
    while ws and _n(ws[0]["text"]) in LEAD_STOP:
        ws = ws[1:]
    seen = set()
    ws = [w for w in ws if not (_n(w["text"]) in seen or seen.add(_n(w["text"])))]
    for w in ws[:max_words]:
        cand = " ".join(out + [_clean(w["text"])])
        if len(cand) > max_chars and out:
            break
        out.append(_clean(w["text"]))
    while out and norm(out[-1]) in BREAK_WORDS | {"de", "do", "da", "o", "a", "os", "as", "um", "uma", "nao", "ne"}:
        out.pop()
    return " ".join(out).upper() if len(out) >= min_words else ""


def scene_from(words: list[dict]) -> dict:
    """Uma cena a partir das palavras de uma frase (todos os textos saem da fala)."""
    at = words[0]["start"]
    text = " ".join(w["text"] for w in words)
    num = _number(words)
    if num:
        i, digits = num
        before = _content(words[max(0, i - 6):i])
        after = []
        for w in words[i + 1:]:
            n = _n(w["text"])
            if n in BREAK_WORDS and after:
                break
            after.append(w)
            if len([a for a in after if _n(a["text"]) not in ("de", "do", "da")]) >= 3 or re.search(r"[,.!?]$", w["text"]):
                break
        hl = _phrase([a for a in after if not re.search(r"\d", a["text"])], 4, 20)
        if hl and not re.search(r"\d", hl):
            return {"kind": "numero", "at": at, "title": _phrase(before[-4:], 4, 20, 2), "number": digits,
                    "highlight": hl, "icon": None, "items": []}
    names = _names(words)
    if len(names) >= 2:
        first_at = names[0][1]
        before = _content([w for w in words if w["start"] < first_at])
        return {"kind": "cartoes", "at": at, "title": _phrase(before[-4:], 4, 20), "number": "",
                "highlight": "", "icon": "flag",
                "items": [{"text": n.upper(), "at": t} for n, t in names[:3]]}
    # destaque: 1ª oração vira o título, as últimas palavras fortes viram o destaque
    clauses = sentences(words)
    first = _content(clauses[0])
    rest = _content([w for c in clauses[1:] for w in c]) if len(clauses) > 1 else first[4:]
    title = _phrase(first, 4, 20, 2)
    hl = _phrase(rest[-3:], 3, 20) if rest else ""
    icon = _icon_for(text)
    if names and names[0][0].upper() not in title:
        hl = names[0][0].upper()
    if not title or (icon == DEFAULT_ICON and not names and not hl):
        return {}
    return {"kind": "destaque", "at": at, "title": title, "number": "", "highlight": hl if hl != title else "",
            "icon": icon, "items": [], "weak": icon == DEFAULT_ICON and not names}


def _visual_score(words: list[dict]) -> float:
    text = " " + norm(" ".join(w["text"] for w in words)) + " "
    s = 0.0
    if _number(words):
        s += 2.0
    n = len(_names(words))
    s += 2.5 if n >= 2 else 0.8 * n
    if any(f" {c} " in text for c in COMPARE):
        s += 1.0
    if _icon_for(text) != DEFAULT_ICON:
        s += 0.8
    return s


def plan(words: list[dict], duration: float, mode: str = "auto", max_blocks: int | None = None,
         use_llm: bool = False, log=None) -> list[dict]:
    """Blocos animados em segundos relativos ao começo do corte (tempo da fonte)."""
    if mode not in ("auto", "inicio") or not words:
        return []
    counts: dict[str, int] = {}
    for w in words:
        t = _clean(w["text"])
        if len(t) > 2 and t[:1].isupper():
            counts[t.lower()] = counts.get(t.lower(), 0) + 1
    _LOCAL.common = {k for k, v in counts.items() if v >= 3}
    sents = sentences(words)
    max_blocks = max_blocks or max(1, min(3, round(duration / 20)))
    cands = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            a, b = sents[i][0]["start"], sents[j][-1]["end"]
            if b - a > MAX_BLOCK_S:
                break
            if b - a >= MIN_BLOCK_S:
                ws = [w for s in sents[i:j + 1] for w in s]
                cands.append((_visual_score(ws) + 0.04 * (b - a), a, b, sents[i:j + 1]))
    chosen = []
    if mode == "inicio":
        first = next((c for c in cands if c[1] <= sents[0][0]["start"] + 0.01), None)
        if first:
            chosen.append(first)
    for c in sorted(cands, key=lambda c: -c[0]):
        if len(chosen) >= max_blocks:
            break
        if c[0] < 1.5 or c[1] < 1.5 or c[2] > duration - 2.0:
            continue
        if all(c[2] + MIN_GAP_S <= o[1] or c[1] >= o[2] + MIN_GAP_S for o in chosen):
            chosen.append(c)
    blocks, texts, block_texts = [], [], []
    for _score, a, b, ss in sorted(chosen, key=lambda c: c[1]):
        scenes = _block_scenes(ss)
        if not scenes:
            continue
        scenes[0]["at"] = a
        ws = [w for c in ss for w in c]
        texts += _scene_texts(scenes, ws, b)
        block_texts += [" ".join(w["text"] for w in ws)] * len(scenes)
        blocks.append({"start": round(a, 3), "end": round(b, 3), "scenes": scenes})
    if use_llm and blocks:
        flat = [sc for blk in blocks for sc in blk["scenes"]]
        refined = _llm_refine(flat, texts, block_texts, log)
        if refined and len(refined) == len(flat):
            it = iter(refined)
            for blk in blocks:
                blk["scenes"] = [next(it) for _ in blk["scenes"]]
    for blk in blocks:
        blk["scenes"] = _round(blk["scenes"])
    return blocks


def _group_scenes(clauses: list[list[dict]], prev: list[dict]) -> list[dict]:
    groups: list[list[dict]] = []
    for c in clauses:
        if groups and (groups[-1][-1]["end"] - groups[-1][0]["start"] < 1.8 or len(groups) >= 3):
            groups[-1] = groups[-1] + c
        else:
            groups.append(list(c))
    out: list[dict] = []
    for g in groups:
        sc = scene_from(g)
        if not sc or (sc.get("weak") and (out or prev)):
            continue                                         # a cena anterior continua na tela
        sc.pop("weak", None)
        out.append(sc)
    return out


def _block_scenes(clauses: list[list[dict]]) -> list[dict]:
    """Cenas de um bloco. Dois ou mais nomes citados no bloco viram uma cena de cartões."""
    ws = [w for c in clauses for w in c]
    names = _names(ws)
    if len(names) >= 2:
        first, last = names[0][1], names[min(2, len(names) - 1)][1]
        pre = [c for c in clauses if c[-1]["end"] <= first]
        mid = [c for c in clauses if c[-1]["end"] > first and c[0]["start"] <= last]
        post = [c for c in clauses if c[0]["start"] > last]
        scenes = _group_scenes(pre, [])
        title = scenes[-1].get("highlight") if scenes else ""
        if not title:
            title = _phrase(_content([w for c in mid for w in c if w["start"] < first])[-4:], 4, 20, 2)
        scenes.append({"kind": "cartoes", "at": mid[0][0]["start"] if mid else first, "title": title or "",
                       "number": "", "highlight": "", "icon": "flag",
                       "items": [{"text": n.upper(), "at": t} for n, t in names[:3]]})
        if post and post[-1][-1]["end"] - post[0][0]["start"] >= 1.8:
            scenes += _group_scenes(post, scenes)
        return scenes
    return _group_scenes(clauses, [])


def _round(scenes: list[dict]) -> list[dict]:
    for sc in scenes:
        sc["at"] = round(sc["at"], 3)
        for it in sc.get("items") or []:
            it["at"] = round(it.get("at", sc["at"]), 3)
    return scenes


def _scene_texts(scenes: list[dict], words: list[dict], end: float) -> list[str]:
    """O trecho falado durante cada cena (da entrada dela até a próxima)."""
    marks = [sc["at"] for sc in scenes[1:]] + [end + 1]
    return [" ".join(w["text"] for w in words if (i == 0 or w["start"] >= scenes[i]["at"] - 0.05)
                     and w["start"] < marks[i]) for i in range(len(scenes))]


def _llm_refine(scenes: list[dict], texts: list[str], block_texts: list[str], log=None) -> list[dict] | None:
    """Pede à IA local (uma chamada por corte) textos melhores para cada cena; cada texto é conferido
    contra a fala do bloco da cena — o que não foi dito é descartado e a cena automática fica."""
    from . import llm, phrases

    if not llm.enabled() or not scenes:
        return None
    icons = sorted(available_icons())
    schema = {"type": "object", "properties": {"cenas": {"type": "array", "minItems": len(texts), "maxItems": len(texts),
              "items": {"type": "object", "properties": {
                  "tipo": {"type": "string", "enum": list(KINDS)}, "titulo": {"type": "string"},
                  "destaque": {"type": "string"}, "numero": {"type": "string"},
                  "itens": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                  "icone": {"type": "string", "enum": icons}},
                  "required": ["tipo", "titulo", "destaque", "numero", "itens", "icone"]}}}, "required": ["cenas"]}
    prompt = ("Você monta cenas de motion graphics para ilustrar a fala de um podcast. Para cada trecho, escolha o tipo "
              "(destaque: título + palavra em destaque + ícone; numero: número grande + o que ele conta; cartoes: até 3 "
              "nomes citados; comparacao: dois itens, o antes e o depois) e escreva textos CURTOS (até 4 palavras) "
              "usando SOMENTE palavras que aparecem no trecho. Não invente nomes, números nem fatos.\n\n"
              + "\n".join(f"[{i}] {t}" for i, t in enumerate(texts)))
    data = llm.generate_json(prompt, "Responda apenas em JSON, em português.", schema=schema,
                             timeout=float(config.get("ai.hook_timeout_s")), options={"temperature": 0.2, "seed": 7})
    if not isinstance(data, dict) or not isinstance(data.get("cenas"), list):
        return None
    out = []
    for sc, d, full in zip(scenes, data["cenas"], block_texts):
        spoken = set(phrases._plain(full).split())

        def from_speech(f: str) -> bool:                 # toda palavra do texto foi dita no bloco
            return all(w in spoken for w in phrases._plain(f).split())

        try:
            fields = [str(d.get("titulo") or ""), str(d.get("destaque") or "")] + [str(x) for x in d.get("itens") or []]
            ok = all(from_speech(f) for f in fields)
            num = str(d.get("numero") or "").strip()
            if num and not (num in re.findall(r"\d+(?:[.,]\d+)?", full) or sc.get("number") == num):
                ok = False
            if not ok or d.get("tipo") not in KINDS:
                out.append(sc)
                continue
            new = dict(sc) | {"kind": d["tipo"], "title": fields[0].upper()[:24], "highlight": fields[1].upper()[:22],
                              "number": num, "icon": d.get("icone") or sc.get("icon")}
            if d["tipo"] in ("cartoes", "comparacao"):
                items = [x.upper()[:18] for x in fields[2:] if x.strip()][:3]
                times = [it["at"] for it in sc.get("items") or []]
                new["items"] = [{"text": t, "at": times[k] if k < len(times) else sc["at"] + 0.6 + 0.8 * k}
                                for k, t in enumerate(items)]
                if len(new["items"]) < 2:
                    out.append(sc)
                    continue
            if d["tipo"] == "numero" and not num:
                out.append(sc)
                continue
            out.append(new)
        except (TypeError, ValueError):
            out.append(sc)
    if log:
        log.info("Motion: IA revisou %d cena(s)", len(out))
    return out


def _num(x, default: float) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def shift_blocks(blocks: list[dict], delta: float, duration: float) -> list[dict]:
    """Corte aparado: move os tempos do roteiro editado para continuar no mesmo trecho da fala."""
    moved = [{"start": b["start"] + delta, "end": b["end"] + delta,
              "scenes": [sc | {"at": sc["at"] + delta, "items": [it | {"at": it["at"] + delta} for it in sc["items"]]}
                         for sc in b["scenes"]]} for b in blocks]
    return validate_blocks(moved, duration)


def validate_blocks(blocks, duration: float) -> list[dict]:
    """Normaliza o roteiro vindo do editor (tempos dentro do corte, textos curtos, ícones conhecidos)."""
    icons = available_icons()
    out = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        a, z = max(0.0, _num(b.get("start"), -1)), min(float(duration), _num(b.get("end"), -1))
        if z - a < 1.5:
            continue
        scenes = []
        for sc in b.get("scenes") or []:
            if not isinstance(sc, dict):
                continue
            kind = sc.get("kind") if sc.get("kind") in KINDS else "destaque"
            at = min(max(_num(sc.get("at"), a), a), z - 0.5)
            items = [{"text": str(it.get("text", ""))[:18].upper(), "at": min(max(_num(it.get("at"), at), at), z - 0.3)}
                     for it in (sc.get("items") or [])[:3] if isinstance(it, dict) and str(it.get("text", "")).strip()]
            scenes.append({"kind": kind, "at": round(at, 3), "title": str(sc.get("title", ""))[:24].upper(),
                           "highlight": str(sc.get("highlight", ""))[:22].upper(),
                           "number": str(sc.get("number", ""))[:6],
                           "icon": sc.get("icon") if sc.get("icon") in icons else DEFAULT_ICON, "items": items})
        scenes.sort(key=lambda s: s["at"])
        if scenes:
            out.append({"start": round(a, 3), "end": round(z, 3), "scenes": scenes})
    return sorted(out, key=lambda b: b["start"])


# ================================================================ desenho
@lru_cache(maxsize=None)
def available_icons() -> frozenset[str]:
    return frozenset(p.stem for p in ICON_DIR.glob("*.png")) | {DEFAULT_ICON}


@lru_cache(maxsize=64)
def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "Poppins-ExtraBold.ttf" if bold else "Poppins-SemiBold.ttf"
    return ImageFont.truetype(str(config.FONTS_DIR / name), size)


def _fit(text: str, size: int, max_w: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    while size > 30 and _font(size, bold).getlength(text) > max_w:
        size -= 4
    return _font(size, bold)


def _shadowed(img: Image.Image, radius: int = 22, offset: int = 18, alpha: int = 50) -> Image.Image:
    pad = radius * 3
    out = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad + offset), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    a = img.getchannel("A").point(lambda v: v * alpha // 255)
    sh.paste(Image.new("RGBA", img.size, THEME["navy"] + (255,)), (pad, pad + offset), a)
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(radius)))
    out.alpha_composite(img, (pad, pad))
    return out


def text_sprite(text: str, size: int, color, max_w: int = 960) -> Image.Image | None:
    if not text:
        return None
    f = _fit(text, size, max_w)
    l, t, r, b = f.getbbox(text)
    img = Image.new("RGBA", (r - l + 8, b - t + 8), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 - l, 4 - t), text, font=f, fill=color)
    return img


def pill_sprite(text: str, coral: bool = False, size: int = 80) -> Image.Image | None:
    if not text:
        return None
    f = _fit(text, size, 900)
    l, t, r, b = f.getbbox(text)
    w, h = r - l + 76, b - t + 44
    img = Image.new("RGBA", (w, h + 14), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg, dark = (THEME["coral"], THEME["coral_dark"]) if coral else (THEME["blue"], THEME["blue_dark"])
    d.rounded_rectangle((0, 14, w - 1, h + 13), 26, fill=dark)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 26, fill=bg)
    d.text((38 - l, 22 - t), text, font=f, fill=THEME["white"])
    return img


@lru_cache(maxsize=128)
def icon_mask(name: str, size: int) -> Image.Image:
    p = ICON_DIR / f"{name}.png"
    if not p.exists():
        p = ICON_DIR / f"{DEFAULT_ICON}.png"
    if not p.exists():                                       # sem ícones instalados: círculo simples
        img = Image.new("L", (size, size), 0)
        ImageDraw.Draw(img).ellipse((size * .2, size * .2, size * .8, size * .8), outline=255, width=max(4, size // 14))
        return img
    with Image.open(p) as im:
        return im.convert("RGBA").getchannel("A").resize((size, size), Image.LANCZOS)


def icon_circle(name: str, diameter: int = 420, color=None) -> Image.Image:
    ring = 16
    img = Image.new("RGBA", (diameter + 2 * ring, diameter + 2 * ring), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, img.width - 1, img.height - 1), fill=(220, 229, 242, 255))
    d.ellipse((ring, ring, ring + diameter, ring + diameter), fill=THEME["white"])
    s = int(diameter * 0.56)
    col = Image.new("RGBA", (s, s), (color or (THEME["gold"] if name == "trophy" else THEME["navy"])) + (255,))
    img.paste(col, ((img.width - s) // 2, (img.height - s) // 2), icon_mask(name, s))
    return _shadowed(img)


def card_sprite(label: str, name: str, icon: str, height: int = 210) -> Image.Image:
    w = 820
    img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, height - 1), 38, fill=THEME["white"])
    c = int(height * 0.62)
    cy = (height - c) // 2
    d.ellipse((44, cy, 44 + c, cy + c), fill=THEME["soft"])
    s = int(c * 0.6)
    img.paste(Image.new("RGBA", (s, s), THEME["blue"] + (255,)), (44 + (c - s) // 2, cy + (c - s) // 2),
              icon_mask(icon, s))
    x = 44 + c + 40
    f = _fit(name, 84, w - x - 30)
    if label:
        d.text((x, height * 0.2), label, font=_font(34, False), fill=THEME["sub"])
        d.text((x, height * 0.38), name, font=f, fill=THEME["navy"])
    else:
        d.text((x, (height - f.size) / 2 - 8), name, font=f, fill=THEME["navy"])
    return _shadowed(img, 18, 14, 40)


@lru_cache(maxsize=4)
def background(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), THEME["bg"] + (255,))
    d = ImageDraw.Draw(img)
    for y in range(22, h, 44):
        for x in range(22, w, 44):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=THEME["dot"])
    vg = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vg).ellipse((-w * 0.25, -h * 0.1, w * 1.25, h * 0.95), fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(160))
    shade = Image.new("RGBA", (w, h), THEME["navy"] + (0,))
    shade.putalpha(vg.point(lambda v: int((255 - v) * 0.10)))
    return Image.alpha_composite(img, shade)


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def _back(x: float) -> float:
    c = 1.9
    x = _clamp(x)
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _out(x: float) -> float:
    return 1 - (1 - _clamp(x)) ** 3


class Element:
    def __init__(self, sprite: Image.Image | None, cx: float, cy: float, t0: float, kind: str = "up"):
        self.sprite, self.cx, self.cy, self.t0, self.kind = sprite, cx, cy, t0, kind

    def draw(self, canvas: Image.Image, t: float, t_exit: float) -> None:
        if self.sprite is None or t < self.t0 or t > t_exit + 0.25:
            return
        p = (t - self.t0) / 0.35
        scale, dx, dy, alpha = 1.0, 0.0, 0.0, 1.0
        if self.kind == "pop":
            scale, alpha = 0.2 + 0.8 * _back(p), _clamp(p * 3)
        elif self.kind == "left":
            dx, alpha = (1 - _back(p)) * -700, _clamp(p * 3)
        else:
            dy, alpha = (1 - _out(p)) * 90, _clamp(p * 2.5)
        q = _clamp((t - t_exit) / 0.25)
        if q > 0:
            alpha *= 1 - q
            scale *= 1 - 0.15 * q
        if alpha <= 0.01:
            return
        spr = self.sprite
        if abs(scale - 1) > 0.01:
            spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BILINEAR)
        if alpha < 0.99:
            spr = spr.copy()
            spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
        canvas.alpha_composite(spr, (int(self.cx - spr.width / 2 + dx), int(self.cy - spr.height / 2 + dy)))


class SceneArt:
    """Elementos de uma cena (tempos em segundos dentro do bloco)."""

    def __init__(self, sc: dict, t0: float, w: int, h: int):
        self.kind, self.t0, self.w = sc["kind"], t0, w
        cx = w / 2
        el = []
        el.append(Element(text_sprite(sc.get("title", ""), 92, THEME["navy"]), cx, 300, t0 + 0.05, "up"))
        self.compare = None
        if self.kind == "numero":
            el.append(Element(text_sprite(sc.get("number", ""), 400, THEME["navy"], 900), cx, 640, t0 + 0.35, "pop"))
            el.append(Element(pill_sprite(sc.get("highlight", "")), cx, 920, t0 + 0.6, "left"))
        elif self.kind == "cartoes":
            items = sc.get("items") or []
            hgt = 210 if len(items) <= 2 else 180
            for k, it in enumerate(items[:3]):
                y = 470 + k * (hgt + 50) + hgt / 2
                el.append(Element(card_sprite("", it["text"], sc.get("icon") or "flag", hgt), cx, y,
                                  max(t0 + 0.3 + 0.25 * k, it["at"] - 0.1), "left"))
        elif self.kind == "comparacao":
            el.append(Element(pill_sprite(sc.get("highlight", ""), coral=True), cx, 430, t0 + 0.35, "pop"))
            items = (sc.get("items") or []) + [{"text": ""}, {"text": ""}]
            self.compare = (items[0]["text"], items[1]["text"], t0 + 0.6)
        else:
            el.append(Element(pill_sprite(sc.get("highlight", "")), cx, 430, t0 + 0.4, "left"))
            el.append(Element(icon_circle(sc.get("icon") or DEFAULT_ICON), cx, 810, t0 + 0.6, "pop"))
        self.elements = el

    def draw(self, canvas: Image.Image, t: float, t_exit: float) -> None:
        for e in self.elements:
            e.draw(canvas, t, t_exit)
        if self.compare and self.t0 <= t <= t_exit + 0.25:
            self._draw_compare(canvas, t, t_exit)

    def _draw_compare(self, canvas: Image.Image, t: float, t_exit: float) -> None:
        a_txt, b_txt, s = self.compare
        fade = 1 - _clamp((t - t_exit) / 0.25)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        base, bw = 1120, 280
        xa, xb = self.w / 2 - 330, self.w / 2 + 50
        ha, hb = 470 * _out((t - s) / 0.5), 200 * _out((t - s - 0.5) / 0.5)
        if ha > 2:
            d.rounded_rectangle((xa, base - ha, xa + bw, base), 28, fill=THEME["blue"])
        if hb > 2:
            d.rounded_rectangle((xb, base - hb, xb + bw, base), 28, fill=THEME["gray"])
        f = _font(52)
        if t > s + 0.3 and a_txt:
            d.text((xa + bw / 2, base - 470 - 40), a_txt, font=_fit(a_txt, 52, 380), fill=THEME["navy"], anchor="mm")
        lab_y = base - 200 - 40
        if t > s + 1.7 and b_txt:
            d.text((xb + bw / 2, lab_y), b_txt, font=_fit(b_txt, 52, 380), fill=THEME["navy"], anchor="mm")
        # seta que se desenha do topo da 1ª barra até a 2ª
        p = _clamp((t - s - 0.9) / 0.7)
        if p > 0:
            pts = []
            x0, y0, x1, y1 = xa + bw + 10, base - 450, xb + 30, lab_y - 60
            for k in range(int(40 * p) + 1):
                u = k / 40
                pts.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * (u ** 1.8)))
            d.line(pts, fill=THEME["coral"], width=16, joint="curve")
            if p >= 1:
                ang = math.atan2(y1 - pts[-3][1], x1 - pts[-3][0])
                for da in (math.radians(150), math.radians(-150)):
                    d.line([(x1, y1), (x1 + 50 * math.cos(ang + da), y1 + 50 * math.sin(ang + da))],
                           fill=THEME["coral"], width=16)
        # rabisco em volta do 2º rótulo
        q = _clamp((t - s - 2.0) / 0.55)
        if q > 0 and b_txt:
            cx, cy = xb + bw / 2, lab_y
            pts = [(cx + 200 * math.cos(a) * (1 + 0.04 * math.sin(3 * a)), cy + 62 * math.sin(a))
                   for a in np.linspace(-2.6, -2.6 + 2 * math.pi * 1.08 * q, max(3, int(60 * q)))]
            d.line(pts, fill=THEME["coral"], width=10, joint="curve")
        if fade < 1:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * fade)))
        canvas.alpha_composite(layer)


def render_block(block_out: dict, path: Path, w: int, h: int, ctx=None) -> Path:
    """Vídeo com transparência do bloco (tempos de saída). Abre e fecha com um círculo."""
    t0, t1 = block_out["start"], block_out["end"]
    dur = t1 - t0
    scenes = block_out["scenes"]
    rel = [dict(sc) | {"items": [dict(it) | {"at": it["at"] - t0} for it in sc.get("items") or []]} for sc in scenes]
    arts = [SceneArt(sc, sc["at"] - t0, w, h) for sc in rel]
    exits = [scenes[k + 1]["at"] - t0 - 0.05 for k in range(len(scenes) - 1)] + [dur + 1.0]
    bg = background(w, h)
    yy, xx = np.ogrid[0:h, 0:w]
    dist = np.sqrt((xx - w / 2) ** 2 + (yy - h / 2) ** 2).astype(np.float32)
    rmax = float(dist.max())
    n = max(1, round(dur * FPS))
    proc = subprocess.Popen([_ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
                             "-r", str(FPS), "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", str(path)],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if ctx:
        ctx.register(proc)
    try:
        for i in range(n):
            t = i / FPS
            frame = bg.copy()
            for art, ex in zip(arts, exits):
                art.draw(frame, t, ex)
            arr = np.asarray(frame).copy()
            r = None
            if t < REVEAL_S:
                r = rmax * _out(t / REVEAL_S)
            elif dur - t < REVEAL_S:
                r = rmax * _out((dur - t) / REVEAL_S)
            if r is not None:
                arr[..., 3] = np.where(dist <= r, 255, 0).astype(np.uint8)
                ring = (dist > r - 10) & (dist <= r)
                arr[ring] = THEME["coral"] + (255,)
            proc.stdin.write(arr.tobytes())
            if ctx and i % 30 == 0:
                ctx.check()
    finally:
        proc.stdin.close()
        proc.wait()
        if ctx:
            ctx.unregister(proc)
    return path


def render_teaser(block_out: dict, path: Path, w: int, h: int, dur: float = 0.9) -> Path:
    """Flash de ~0,9 s da cena mais forte do bloco (já montada), para abrir o vídeo."""
    scenes = block_out["scenes"]
    best = max(range(len(scenes)), key=lambda k: {"numero": 3, "comparacao": 2.5, "cartoes": 2, "destaque": 1}
               .get(scenes[k]["kind"], 0))
    sc = dict(scenes[best]) | {"at": 0.0}
    sc["items"] = [dict(it) | {"at": 0.0} for it in sc.get("items") or []]
    art = SceneArt(sc, -3.0, w, h)                            # tudo já entrou
    still = background(w, h).copy()
    art.draw(still, 0.0, 99)
    yy, xx = np.ogrid[0:h, 0:w]
    dist = np.sqrt((xx - w / 2) ** 2 + (yy - h / 2) ** 2).astype(np.float32)
    rmax = float(dist.max())
    n = max(1, round(dur * FPS))
    proc = subprocess.Popen([_ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}",
                             "-r", str(FPS), "-i", "pipe:0", "-c:v", "qtrle", "-pix_fmt", "argb", str(path)],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for i in range(n):
            t = i / FPS
            z = 1 + 0.05 * t / dur
            fr = still.resize((int(w * z), int(h * z)), Image.BILINEAR).crop(
                (int((w * z - w) / 2), int((h * z - h) / 2), int((w * z - w) / 2) + w, int((h * z - h) / 2) + h))
            arr = np.asarray(fr).copy()
            if dur - t < 0.2:
                r = rmax * _out((dur - t) / 0.2)
                arr[..., 3] = np.where(dist <= r, 255, 0).astype(np.uint8)
            proc.stdin.write(arr.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    return path


def appear_times(block_out: dict) -> list[float]:
    """Instantes (tempo de saída) em que elementos entram: para os sons de "pop"."""
    out = [block_out["start"] + 0.02]
    for sc in block_out["scenes"]:
        out += [sc["at"] + 0.35]
        out += [it["at"] for it in sc.get("items") or []]
    return sorted(set(round(t, 3) for t in out if block_out["start"] <= t < block_out["end"]))


def _ffmpeg() -> str:
    from .ffmpeg import ffmpeg_bin

    return ffmpeg_bin()


BUBBLE = 250


def bubble_filter(inp: str, outp: str, out_w: int, out_h: int) -> str:
    """Rosto de quem fala num círculo com borda branca (recorte do vídeo já enquadrado)."""
    s, c = BUBBLE, BUBBLE / 2
    side = int(out_w * 0.7)
    y = int(max(0, min(out_h * 0.36 - side / 2, out_h - side)))
    return (f"[{inp}]crop={side}:{side}:{(out_w - side) // 2}:{y},scale={s}:{s},format=rgba,"
            f"geq=r='if(gt(hypot(X-{c},Y-{c}),{c - 9}),255,r(X,Y))':g='if(gt(hypot(X-{c},Y-{c}),{c - 9}),255,g(X,Y))':"
            f"b='if(gt(hypot(X-{c},Y-{c}),{c - 9}),255,b(X,Y))':a='if(lte(hypot(X-{c},Y-{c}),{c - 1}),255,0)'[{outp}]")
