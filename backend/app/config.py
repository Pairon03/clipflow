"""Configuração do ClipFlow Studio.

Ordem de prioridade (maior vence):
1. Ajustes salvos pela interface (tabela `settings` do SQLite) — apenas chaves editáveis.
2. Variáveis de ambiente CLIPFLOW_CONFIG (caminho do toml) e CLIPFLOW_DATA_DIR.
3. config.toml na raiz do projeto.
4. Padrões definidos em DEFAULTS.
"""
from __future__ import annotations

import copy
import os
import threading
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MODELS_DIR = ASSETS_DIR / "models"

DEFAULTS: dict[str, dict[str, Any]] = {
    "server": {"host": "127.0.0.1", "port": 8000, "access_token": ""},
    "storage": {"data_dir": "ClipFlowStudio"},
    "limits": {
        "max_upload_mb": 4096,
        "max_source_minutes": 240,
        "max_concurrent_jobs": 1,
        "max_attempts": 2,
        "max_clips_per_project": 20,
    },
    "transcription": {
        "engine": "faster-whisper",
        "model": "small",
        "device": "auto",
        "compute_type": "int8",
        "language": "pt",
        "vad_filter": True,
    },
    "ai": {
        "ollama_enabled": False,
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_model": "llama3.2:3b",
        "ollama_timeout_s": 120,
        "hook_timeout_s": 180,   # avaliação de ganchos pela IA; acima disso usa só a heurística
        "map_blocks": 6,         # quantos blocos do mapa do episódio a IA avalia (0 = só regras)
    },
    "render": {
        "width": 1080,
        "height": 1920,
        "fps_max": 30,
        "video_preset": "veryfast",
        "crf": 20,
        "audio_bitrate": "160k",
        "loudnorm": True,
        "face_tracking": True,
        "verify_decode": True,
    },
    "concat": {"path": ""},
    "branding": {
        "channel_name": "",
        "channel_handle": "",
        "tweet_text": "Você achou a melhor página de cortes do TikTok",
        "tweet_mode": "fixo",   # fixo: usa tweet_text | resumo: resume o trecho de cada corte
    },
    "censor": {"extra_words": ""},  # palavras extras a silenciar, separadas por vírgula
    "youtube": {
        "category_id": "24",            # Entretenimento
        "notify_subscribers": True,
        "times": "12:00, 19:00",        # horários padrão do agendamento (um vídeo por horário)
    },
}

# Chaves que a interface pode alterar em tempo de execução, com o tipo esperado.
EDITABLE: dict[str, type] = {
    "limits.max_upload_mb": int,
    "limits.max_source_minutes": int,
    "limits.max_concurrent_jobs": int,
    "limits.max_attempts": int,
    "transcription.model": str,
    "transcription.device": str,
    "transcription.compute_type": str,
    "transcription.language": str,
    "transcription.vad_filter": bool,
    "ai.ollama_enabled": bool,
    "ai.ollama_url": str,
    "ai.ollama_model": str,
    "ai.hook_timeout_s": int,
    "ai.map_blocks": int,
    "render.video_preset": str,
    "render.crf": int,
    "render.loudnorm": bool,
    "render.face_tracking": bool,
    "render.verify_decode": bool,
    "concat.path": str,
    "branding.channel_name": str,
    "branding.channel_handle": str,
    "branding.tweet_text": str,
    "branding.tweet_mode": str,
    "censor.extra_words": str,
    "youtube.category_id": str,
    "youtube.notify_subscribers": bool,
    "youtube.times": str,
}

ALLOWED_VALUES: dict[str, set] = {
    "transcription.model": {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"},
    "transcription.device": {"auto", "cpu", "cuda"},
    "transcription.compute_type": {"int8", "int8_float16", "float16", "float32"},
    "render.video_preset": {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"},
    "branding.tweet_mode": {"fixo", "resumo"},
    "youtube.category_id": {"17", "20", "22", "23", "24", "25", "26", "27"},
}

_lock = threading.Lock()
_file_config: dict[str, dict[str, Any]] | None = None
_overrides: dict[str, Any] = {}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_file_config() -> dict[str, dict[str, Any]]:
    path = Path(os.environ.get("CLIPFLOW_CONFIG", PROJECT_ROOT / "config.toml"))
    cfg = copy.deepcopy(DEFAULTS)
    if path.is_file():
        with path.open("rb") as fh:
            cfg = _deep_merge(cfg, tomllib.load(fh))
    if os.environ.get("CLIPFLOW_DATA_DIR"):
        cfg["storage"]["data_dir"] = os.environ["CLIPFLOW_DATA_DIR"]
    return cfg


def reload() -> None:
    global _file_config
    with _lock:
        _file_config = _load_file_config()
        _overrides.clear()


def get(key: str) -> Any:
    """Lê uma configuração no formato 'secao.chave'."""
    global _file_config
    with _lock:
        if _file_config is None:
            _file_config = _load_file_config()
        if key in _overrides:
            return _overrides[key]
        section, name = key.split(".", 1)
        return _file_config[section][name]


def all_settings() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for section, values in DEFAULTS.items():
        out[section] = {name: get(f"{section}.{name}") for name in values}
    out["server"]["access_token"] = "***" if out["server"]["access_token"] else ""
    return out


def coerce(key: str, value: Any) -> Any:
    """Valida e converte um valor vindo da interface. Lança ValueError se inválido."""
    if key not in EDITABLE:
        raise ValueError(f"Configuração não editável: {key}")
    typ = EDITABLE[key]
    if typ is bool:
        if isinstance(value, bool):
            v = value
        elif str(value).lower() in {"1", "true", "sim", "yes", "on"}:
            v = True
        elif str(value).lower() in {"0", "false", "nao", "não", "no", "off"}:
            v = False
        else:
            raise ValueError(f"Valor booleano inválido para {key}")
    elif typ is int:
        v = int(value)
        if v < 0:
            raise ValueError(f"Valor negativo para {key}")
    else:
        v = str(value).strip()
    if key in ALLOWED_VALUES and v not in ALLOWED_VALUES[key]:
        raise ValueError(f"Valor não permitido para {key}: {v}")
    if key == "ai.ollama_url" and not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError("URL do Ollama deve começar com http:// ou https://")
    if key in ("branding.channel_name", "branding.channel_handle") and len(v) > 40:
        raise ValueError("Nome/@ do canal muito longo (máx. 40 caracteres)")
    if key == "branding.tweet_text" and len(v) > 140:
        raise ValueError("Frase do tweet muito longa (máx. 140 caracteres)")
    if key == "censor.extra_words" and len(v) > 2000:
        raise ValueError("Lista de palavras muito longa (máx. 2000 caracteres)")
    if key == "concat.path" and v:
        p = Path(v)
        if not (p.is_file() and p.name.lower().startswith("concat")):
            raise ValueError("Caminho do Concat inválido: aponte para o executável concat (ou concat.exe)")
    if key == "ai.hook_timeout_s" and not 10 <= v <= 600:
        raise ValueError("Tempo da IA para ganchos deve ficar entre 10 e 600 s")
    if key == "youtube.times":
        parse_times(v)
    if key == "ai.map_blocks" and not 0 <= v <= 30:
        raise ValueError("Blocos avaliados pela IA deve ficar entre 0 e 30")
    if key == "limits.max_concurrent_jobs" and not 1 <= v <= 8:
        raise ValueError("Tarefas simultâneas deve estar entre 1 e 8")
    return v


def parse_times(text: str) -> list[str]:
    """'12:00, 19:00' -> ['12:00', '19:00'] (ordenados, sem repetidos). Lança ValueError se inválido."""
    import re

    out = set()
    for part in re.split(r"[,;\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"([01]?\d|2[0-3])[:h]([0-5]\d)?", part)
        if not m:
            raise ValueError(f"Horário inválido: {part} (use 12:00, 19:00)")
        out.add(f"{int(m.group(1)):02d}:{m.group(2) or '00'}")
    if not out or len(out) > 12:
        raise ValueError("Informe de 1 a 12 horários (ex.: 12:00, 19:00)")
    return sorted(out)


def set_override(key: str, value: Any) -> None:
    with _lock:
        _overrides[key] = value


def data_dir() -> Path:
    p = Path(get("storage.data_dir"))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()
