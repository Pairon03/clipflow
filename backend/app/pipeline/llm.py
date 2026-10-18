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


def generate_json(prompt: str, system: str = "", timeout: float | None = None) -> dict | list | None:
    """Pede uma resposta JSON ao modelo local. Retorna None em qualquer falha."""
    if not enabled():
        return None
    url = config.get("ai.ollama_url").rstrip("/") + "/api/generate"
    body = json.dumps({
        "model": config.get("ai.ollama_model"),
        "prompt": prompt,
        "system": system,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.3},
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
