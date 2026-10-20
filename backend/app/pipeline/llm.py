"""Cliente opcional para IA local via Ollama (gratuito, roda no seu computador).

Tudo aqui é opcional: se o Ollama estiver desligado nas configurações ou não
responder, o pipeline continua com o motor heurístico.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .. import config

log = logging.getLogger("clipflow.llm")


def enabled() -> bool:
    return bool(config.get("ai.ollama_enabled"))


def status() -> dict:
    url = config.get("ai.ollama_url").rstrip("/")
    out = {"enabled": enabled(), "url": url, "model": config.get("ai.ollama_model"),
           "reachable": False, "model_installed": False}
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode())
        out["reachable"] = True
        names = {m.get("name") for m in tags.get("models", [])}
        out["model_installed"] = out["model"] in names or f"{out['model']}:latest" in names
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return out


def generate_json(prompt: str, system: str = "", timeout: float | None = None,
                  options: dict | None = None, schema: dict | None = None) -> dict | list | None:
    """Pede uma resposta JSON ao modelo local. Retorna None em qualquer falha."""
    if not enabled():
        return None
    url = config.get("ai.ollama_url").rstrip("/") + "/api/generate"
    body = json.dumps({
        "model": config.get("ai.ollama_model"),
        "prompt": prompt,
        "system": system,
        "format": schema or "json",   # com schema, o Ollama (≥ 0.5) só gera JSON nesse formato
        "stream": False,
        "options": {"temperature": 0.3} | (options or {}),
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.get("ai.ollama_timeout_s")) as r:
            data = json.loads(r.read().decode())
        return json.loads(data.get("response", ""))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        log.warning("Ollama indisponível ou resposta inválida: %s", exc)
        return None


RERANK_SYSTEM = (
    "Você é um editor de vídeo experiente que escolhe trechos de podcasts para YouTube Shorts. "
    "Avalie cada trecho somente pelo texto fornecido. Não invente informações. "
    "Responda apenas em JSON."
)


def rerank(candidates: list[dict]) -> dict[int, dict] | None:
    """Recebe [{'id', 'text'}] e devolve {id: {'nota': 0-10, 'motivo': str}} ou None."""
    if not candidates:
        return None
    listing = "\n\n".join(f"[{c['id']}] {c['text'][:900]}" for c in candidates)
    prompt = (
        "Avalie os trechos abaixo para virar Shorts. Para cada um, dê uma nota de 0 a 10 considerando: "
        "se faz sentido sozinho (sem contexto anterior), se tem começo/meio/fim, se é interessante, "
        "e se o corte NÃO distorce a opinião de quem fala.\n"
        'Formato: {"avaliacoes": [{"id": <número>, "nota": <0-10>, "motivo": "<frase curta>"}]}\n\n'
        + listing
    )
    data = generate_json(prompt, RERANK_SYSTEM)
    if not isinstance(data, dict) or not isinstance(data.get("avaliacoes"), list):
        return None
    out: dict[int, dict] = {}
    valid_ids = {c["id"] for c in candidates}
    for item in data["avaliacoes"]:
        try:
            cid = int(item["id"])
            nota = float(item["nota"])
        except (KeyError, TypeError, ValueError):
            continue
        if cid in valid_ids and 0 <= nota <= 10:
            out[cid] = {"nota": nota, "motivo": str(item.get("motivo", ""))[:200]}
    return out or None


HOOK_SYSTEM = (
    "Você é editor-chefe de uma página de cortes de podcast no TikTok e YouTube Shorts. O vídeo começa com um "
    "GANCHO: uma frase de um momento posterior toca primeiro; depois o vídeo volta ao começo da história, a mesma "
    "frase aparece de novo no lugar original (payoff) e a história termina. Avalie candidatos a gancho SOMENTE "
    "pela transcrição. Um bom gancho desperta curiosidade sem entregar a conclusão, é entendido por quem não viu "
    "a entrevista e não muda de sentido fora do contexto. Responda apenas em JSON."
)


def evaluate_hooks(transcript_text: str, candidates: list[dict], timeout: float | None = None) -> dict[int, dict] | None:
    """Notas 0–10 da IA local para cada candidato a gancho, nos 7 critérios de hooks.CRITERIA.

    Recebe [{'id', 'text'}] (trechos literais da fala) e devolve
    {id: {'scores': {critério: nota}, 'motivo': str, 'spoiler': bool}} ou None em qualquer falha.
    A IA só avalia; o texto do gancho é sempre o trecho original.
    """
    from .hooks import CRITERIA

    if not candidates:
        return None
    listing = "\n".join(f"[{c['id']}] \"{c['text'][:220]}\"" for c in candidates)
    n = len(candidates)
    prompt = (
        f"Transcrição do corte:\n\"\"\"{transcript_text[:2600]}\"\"\"\n\n"
        f"Candidatos a gancho ({n}):\n{listing}\n\n"
        "Compare os candidatos ENTRE SI e dê a cada um 7 notas de 0 a 10, nesta ordem: curiosidade que desperta; "
        "clareza para quem não conhece a entrevista; impacto emocional; relevância para a história; vontade de "
        "continuar assistindo; fidelidade (10 = o sentido não muda fora do contexto); payoff (a frase ganha "
        "significado quando reaparece no lugar original e há desfecho depois). Use a escala inteira: 2 a 4 para "
        "narração comum, 5 a 6 razoável, 7 a 8 bom, 9 a 10 excepcional; não dê a mesma nota para todos. "
        "spoiler=true quando a frase revela a resposta ou o desfecho da história (ex.: a revelação final).\n"
        "Antes de avaliar, escreva em \"desfecho\" (até 15 palavras) qual é a revelação ou conclusão da história. "
        "Um candidato só é spoiler se contar ESSE desfecho.\n"
        f"Depois responda com {n} itens (ids 0 a {n - 1}): \"n\" com as 7 notas na ordem acima, \"spoiler\" e \"m\" "
        "com até 8 palavras, escritas por você, sobre o que essa frase tem de bom ou de fraco."
    )
    schema = {"type": "object", "required": ["desfecho", "a"], "properties": {
        "desfecho": {"type": "string", "maxLength": 140},
        "a": {
        "type": "array", "minItems": n, "maxItems": n, "items": {
            "type": "object", "required": ["id", "n", "spoiler", "m"], "properties": {
                "id": {"type": "integer", "enum": [c["id"] for c in candidates]},
                "n": {"type": "array", "minItems": 7, "maxItems": 7,
                      "items": {"type": "integer", "minimum": 0, "maximum": 10}},
                "spoiler": {"type": "boolean"},
                "m": {"type": "string", "maxLength": 80}}}}}}
    # o desfecho vem primeiro: o modelo identifica a conclusão antes de julgar o que a entrega
    data = generate_json(prompt, HOOK_SYSTEM, timeout=timeout, schema=schema,
                         options={"temperature": 0.2, "seed": 7, "num_predict": 700})
    if not isinstance(data, dict):
        return None
    items = data.get("a") or data.get("avaliacoes")
    if items is None and all(str(k).isdigit() for k in data):    # variação: {"0": {...}, "1": {...}}
        items = [v | {"id": k} for k, v in data.items() if isinstance(v, dict)]
    if not isinstance(items, list):
        return None
    valid = {c["id"] for c in candidates}
    out: dict[int, dict] = {}
    for item in items:
        try:
            cid = int(item["id"])
            notes = [float(x) for x in item["n"]]
        except (KeyError, TypeError, ValueError):
            continue
        if cid not in valid or len(notes) != len(CRITERIA) or not all(0 <= x <= 10 for x in notes):
            continue
        motivo = str(item.get("m") or item.get("motivo") or "").strip()
        if motivo.strip(". ") == "" or motivo.lower() in {"motivo curto", "seu motivo", "<seu motivo>"}:
            motivo = ""                                    # o modelo só repetiu o exemplo do formato
        out[cid] = {"scores": dict(zip(CRITERIA, notes)), "spoiler": bool(item.get("spoiler")), "motivo": motivo[:200]}
    if len(out) != len(valid):
        log.warning("IA local avaliou %d de %d candidatos a gancho; usando a heurística", len(out), len(valid))
        return None
    totals = [sum(v["scores"].values()) for v in out.values()]
    if len(out) >= 3 and max(totals) - min(totals) < 3.5:   # menos de 0,5 ponto de média entre o melhor e o pior
        log.warning("IA local deu notas iguais aos candidatos a gancho; usando a heurística")
        return None
    return out


METADATA_SYSTEM = (
    "Você é social media de uma página de cortes de podcast no TikTok, Reels e YouTube Shorts, em português do "
    "Brasil. Seu texto precisa ser ESPECÍFICO do trecho (cite o assunto concreto, nomes, números) e nunca "
    "genérico como 'olha esse trecho'. NÃO transcreva a fala inteira. "
    "Regras obrigatórias: use apenas o que está na transcrição; não invente fatos nem falas; nada de clickbait "
    "enganoso; títulos com no máximo 70 caracteres; a 'frase' da caixa deve ser COPIADA da transcrição "
    "(pode apenas tirar muletas como né, tipo, aí, cara) e precisa fazer sentido sozinha. "
    "Exemplo de resposta para um trecho em que Craque Neto critica o Neymar no Podpah: "
    '{"titulos": ["Craque Neto: Neymar desperdiçou a carreira", "O que faltou para o Neymar, segundo Craque Neto", '
    '"Talento sem disciplina não vale nada"], '
    '"gancho": "🔥 Craque Neto não aliviou pro Neymar", '
    '"contexto": "No Podpah, ele diz que o talento do Neymar era maior que o de Messi e Cristiano, mas faltou disciplina.", '
    '"chamada": "Você concorda com o Craque Neto? Comenta 👇", '
    '"caixa": {"chamada": "Craque Neto sobre o Neymar:", "frase": "Talento sem disciplina não vale nada"}, '
    '"manchete": "Craque Neto diz que Neymar trocou a carreira pela balada", '
    '"hashtags": ["#neymar", "#futebol", "#craqueneto"], "palavras_chave": ["neymar", "disciplina"]}. '
    "Responda somente em JSON."
)


def metadata(transcript_text: str, source_title: str) -> dict | None:
    prompt = (
        f"Vídeo de origem: {source_title}\nTranscrição do corte:\n\"\"\"{transcript_text[:3000]}\"\"\"\n\n"
        'Formato: {"titulos": ["", "", ""], "gancho": "1ª linha, com 1 emoji, até 90 caracteres", '
        '"contexto": "1 frase: quem fala e sobre o quê, com o detalhe concreto do trecho, até 160 caracteres", '
        '"chamada": "pergunta para comentar ligada ao assunto, até 80 caracteres", '
        '"caixa": {"chamada": "até 40 caracteres, terminando com dois-pontos", '
        '"frase": "frase copiada da transcrição, até 80 caracteres"}, '
        '"manchete": "resumo do trecho em 3ª pessoa, até 100 caracteres", '
        '"hashtags": ["#..."], "palavras_chave": ["..."]}'
    )
    data = generate_json(prompt, METADATA_SYSTEM)
    return data if isinstance(data, dict) else None
