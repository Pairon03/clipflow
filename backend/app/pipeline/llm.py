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
    "Você é social media de cortes de podcast e cria títulos e descrições para TikTok, Reels e YouTube Shorts "
    "em português do Brasil. A descrição deve ser chamativa: começa com um gancho curto com 1 emoji, depois "
    "uma frase que gere curiosidade e termina com uma chamada para comentar ou seguir. NÃO transcreva a fala. "
    "Regras obrigatórias: use apenas informações presentes na transcrição; não invente declarações nem "
    "atribua falas que não existem; nada de clickbait enganoso; títulos com no máximo 70 caracteres. "
    "Responda em JSON."
)


def metadata(transcript_text: str, source_title: str) -> dict | None:
    prompt = (
        f"Vídeo de origem: {source_title}\nTranscrição do corte:\n\"\"\"{transcript_text[:3000]}\"\"\"\n\n"
        'Formato: {"titulos": ["", "", ""], "manchete": "resumo do trecho em 3ª pessoa, até 100 caracteres", '
        '"descricao": "gancho + curiosidade + chamada, até 3 linhas", '
        '"hashtags": ["#..."], "palavras_chave": ["..."], "texto_curto": "1 frase para publicação"}'
    )
    data = generate_json(prompt, METADATA_SYSTEM)
    return data if isinstance(data, dict) else None
