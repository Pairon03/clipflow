"""Conexão com a API oficial do YouTube (Data API v3): autorização OAuth e envio de vídeos.

- Credencial do tipo "App para computador" criada pelo usuário no Google Cloud (arquivo client_secret.json).
- Autorização pelo navegador com redirecionamento para o próprio ClipFlow (http://127.0.0.1:<porta>) e PKCE.
- O token fica só na pasta de dados (youtube/token.json); nunca é devolvido pela API do ClipFlow.
- Envio retomável (resumable upload) em partes: uma queda de conexão continua de onde parou.

Só biblioteca padrão (urllib), sem dependências novas.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import storage

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
# envio de vídeos + leitura do próprio canal (para mostrar qual canal está conectado)
SCOPES = ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly")
CHUNK = 8 * 1024 * 1024          # partes do envio (múltiplo de 256 KiB, exigência do Google)
TIMEOUT = 120
STATE_TTL = 15 * 60


class YouTubeError(Exception):
    """Erro da API. kind: auth (reconectar), quota (limite diário), retry (temporário), fatal."""

    def __init__(self, message: str, kind: str = "fatal", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


# ------------------------------------------------------------------ arquivos
def _dir() -> Path:
    d = storage.root() / "youtube"
    d.mkdir(parents=True, exist_ok=True)
    return d


def client_path() -> Path:
    return _dir() / "client_secret.json"


def token_path() -> Path:
    return _dir() / "token.json"


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def save_client(raw: bytes) -> dict:
    """Valida e guarda o client_secret.json baixado do Google Cloud."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Arquivo inválido: envie o JSON baixado em Google Cloud › Credenciais")
    if not isinstance(data, dict):
        raise ValueError("Arquivo inválido: envie o JSON baixado em Google Cloud › Credenciais")
    if "web" in data and "installed" not in data:
        raise ValueError("Essa credencial é do tipo \"Aplicativo da Web\". Crie uma do tipo \"App para computador\".")
    info = data.get("installed")
    if not isinstance(info, dict) or not info.get("client_id") or not info.get("client_secret"):
        raise ValueError("Credencial sem client_id/client_secret. Baixe de novo o JSON do \"App para computador\".")
    if not str(info["client_id"]).endswith(".apps.googleusercontent.com"):
        raise ValueError("client_id não parece ser do Google")
    clean = {"client_id": str(info["client_id"]), "client_secret": str(info["client_secret"]),
             "project_id": str(info.get("project_id", ""))}
    _write_private(client_path(), clean)
    return clean


def client() -> dict | None:
    return _read(client_path())


def token() -> dict | None:
    return _read(token_path())


def disconnect(revoke: bool = True) -> None:
    tok = token()
    if revoke and tok and tok.get("refresh_token"):
        try:
            _post_form(REVOKE_URL, {"token": tok["refresh_token"]})
        except YouTubeError:
            pass                                     # sem internet: apaga o token local mesmo assim
    storage.remove_quietly(token_path())


def remove_client() -> None:
    disconnect()
    storage.remove_quietly(client_path())


# ------------------------------------------------------------------ HTTP
def _request(method: str, url: str, *, data: bytes | None = None, headers: dict | None = None,
             timeout: float = TIMEOUT) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise YouTubeError(f"Sem conexão com o Google ({reason})", "retry")


def _json(body: bytes) -> dict:
    try:
        out = json.loads(body.decode("utf-8")) if body else {}
        return out if isinstance(out, dict) else {}
    except (UnicodeDecodeError, ValueError):
        return {}


def _api_error(status: int, body: bytes) -> YouTubeError:
    data = _json(body)
    err = data.get("error")
    reason, message = "", ""
    if isinstance(err, dict):
        message = str(err.get("message") or "")
        errs = err.get("errors") or []
        if errs and isinstance(errs[0], dict):
            reason = str(errs[0].get("reason") or "")
    elif isinstance(err, str):                      # erros do OAuth: {"error": "invalid_grant", ...}
        reason, message = err, str(data.get("error_description") or err)
    if reason in ("quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded", "rateLimitExceeded",
                  "userRateLimitExceeded"):
        return YouTubeError("Limite diário de envios do YouTube atingido. O ClipFlow tenta de novo amanhã.",
                            "quota", status)
    if status == 401 or reason in ("invalid_grant", "unauthorized_client", "authError"):
        return YouTubeError("A autorização do YouTube expirou ou foi revogada. Conecte a conta de novo.",
                            "auth", status)
    if reason in ("youtubeSignupRequired", "channelNotFound"):
        return YouTubeError("Esta conta Google não tem canal no YouTube. Crie o canal e conecte de novo.",
                            "auth", status)
    if status == 403 and reason in ("forbidden", "insufficientPermissions", "accessNotConfigured"):
        extra = " Ative a \"YouTube Data API v3\" no seu projeto do Google Cloud." \
            if reason == "accessNotConfigured" else ""
        return YouTubeError(f"O Google recusou o pedido ({message or reason}).{extra}", "fatal", status)
    if status >= 500 or status == 429:
        return YouTubeError(f"O YouTube está instável agora (HTTP {status})", "retry", status)
    detail = message or reason or f"HTTP {status}"
    return YouTubeError(f"O YouTube recusou o envio: {detail}", "fatal", status)


def _post_form(url: str, fields: dict) -> dict:
    status, _h, body = _request("POST", url, data=urllib.parse.urlencode(fields).encode(),
                                headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    if status >= 400:
        raise _api_error(status, body)
    return _json(body)


# ------------------------------------------------------------------ OAuth
_pending: dict[str, tuple[str, str, float]] = {}   # state -> (verifier, redirect_uri, criado em)
_pending_lock = threading.Lock()


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def auth_url(port: int) -> str:
    c = client()
    if not c:
        raise YouTubeError("Envie primeiro a credencial (client_secret.json) do Google Cloud", "fatal")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    uri = redirect_uri(port)
    now = time.time()
    with _pending_lock:
        for k in [k for k, v in _pending.items() if now - v[2] > STATE_TTL]:
            _pending.pop(k, None)
        _pending[state] = (verifier, uri, now)
    params = {
        "client_id": c["client_id"], "redirect_uri": uri, "response_type": "code", "scope": " ".join(SCOPES),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent",          # garante o refresh_token
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def is_pending_state(state: str | None) -> bool:
    with _pending_lock:
        return bool(state) and state in _pending


def finish_auth_cancelled(state: str | None) -> None:
    with _pending_lock:
        _pending.pop(state or "", None)


def finish_auth(state: str, code: str) -> dict:
    with _pending_lock:
        item = _pending.pop(state, None)
    if not item or time.time() - item[2] > STATE_TTL:
        raise YouTubeError("Pedido de autorização expirado. Clique em \"Conectar\" de novo.", "auth")
    verifier, uri, _ = item
    c = client()
    if not c:
        raise YouTubeError("Credencial do Google Cloud não encontrada", "fatal")
    data = _post_form(TOKEN_URL, {
        "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if not data.get("refresh_token"):
        raise YouTubeError("O Google não devolveu a autorização permanente. Tente conectar de novo.", "auth")
    granted = set(str(data.get("scope", "")).split())
    if SCOPES[0] not in granted:
        raise YouTubeError("A permissão para enviar vídeos não foi concedida. Marque todas as caixas ao "
                           "autorizar.", "auth")
    tok = {"refresh_token": data["refresh_token"], "access_token": data.get("access_token", ""),
           "expires_at": time.time() + float(data.get("expires_in", 3600)), "scope": data.get("scope", "")}
    _write_private(token_path(), tok)
    try:
        tok["channel"] = fetch_channel(tok["access_token"])
    except YouTubeError:
        tok["channel"] = None
    _write_private(token_path(), tok)
    return tok


_refresh_lock = threading.Lock()


def access_token() -> str:
    with _refresh_lock:
        tok = token()
        if not tok or not tok.get("refresh_token"):
            raise YouTubeError("Conta do YouTube não conectada", "auth")
        if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 120:
            return tok["access_token"]
        c = client()
        if not c:
            raise YouTubeError("Credencial do Google Cloud não encontrada", "auth")
        data = _post_form(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c["client_secret"],
                                      "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        tok["access_token"] = data.get("access_token", "")
        tok["expires_at"] = time.time() + float(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            tok["refresh_token"] = data["refresh_token"]
        _write_private(token_path(), tok)
        return tok["access_token"]


def fetch_channel(access: str | None = None) -> dict | None:
    access = access or access_token()
    status, _h, body = _request("GET", f"{API_URL}/channels?part=snippet&mine=true",
                                headers={"Authorization": f"Bearer {access}"}, timeout=30)
    if status >= 400:
        raise _api_error(status, body)
    items = _json(body).get("items") or []
    if not items:
        raise YouTubeError("Esta conta Google não tem canal no YouTube. Crie o canal e conecte de novo.", "auth")
    sn = items[0].get("snippet") or {}
    thumbs = sn.get("thumbnails") or {}
    thumb = (thumbs.get("default") or {}).get("url", "")
    return {"id": items[0].get("id", ""), "title": sn.get("title", ""), "handle": sn.get("customUrl", ""),
            "thumbnail": thumb}


def mark_invalid(reason: str) -> None:
    """A autorização foi recusada pelo Google: fica marcada até o usuário conectar de novo."""
    tok = token()
    if tok:
        tok["invalid"] = reason
        _write_private(token_path(), tok)


def status() -> dict:
    c, tok = client(), token()
    has_token = bool(tok and tok.get("refresh_token"))
    invalid = bool(has_token and tok.get("invalid"))
    return {"has_client": bool(c), "project_id": (c or {}).get("project_id", ""),
            "connected": has_token and not invalid, "needs_reconnect": invalid,
            "problem": (tok or {}).get("invalid") or "", "channel": (tok or {}).get("channel")}


# ------------------------------------------------------------------ envio
def start_upload(metadata: dict, size: int, notify: bool = True) -> str:
    """Abre uma sessão de envio retomável e devolve a URL dela (válida por cerca de uma semana)."""
    q = urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status",
                                "notifySubscribers": "true" if notify else "false"})
    status_, headers, body = _request(
        "POST", f"{UPLOAD_URL}?{q}", data=json.dumps(metadata).encode(),
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)}, timeout=60)
    if status_ >= 400:
        raise _api_error(status_, body)
    location = {k.lower(): v for k, v in headers.items()}.get("location")
    if not location:
        raise YouTubeError("O YouTube não abriu a sessão de envio", "retry", status_)
    return location


def _confirmed_bytes(headers: dict) -> int:
    rng = {k.lower(): v for k, v in headers.items()}.get("range")    # "bytes=0-1048575"
    if not rng or "-" not in rng:
        return 0
    return int(rng.rsplit("-", 1)[1]) + 1


def query_offset(session_url: str, size: int) -> tuple[int, dict | None]:
    """Pergunta quanto do arquivo o YouTube já recebeu. Devolve (bytes, vídeo se já terminou)."""
    status_, headers, body = _request("PUT", session_url, data=b"",
                                      headers={"Authorization": f"Bearer {access_token()}",
                                               "Content-Range": f"bytes */{size}"}, timeout=60)
    if status_ in (200, 201):
        return size, _json(body)
    if status_ == 308:
        return _confirmed_bytes(headers), None
    if status_ in (404, 410):
        raise YouTubeError("A sessão de envio expirou; começando de novo", "restart", status_)
    raise _api_error(status_, body)


def upload_file(session_url: str, path: Path, offset: int = 0,
                on_progress: Callable[[int, int], None] | None = None,
                is_cancelled: Callable[[], bool] | None = None) -> dict:
    """Envia o arquivo em partes a partir de `offset`. Devolve o recurso do vídeo criado."""
    size = path.stat().st_size
    stalls = 0
    with path.open("rb") as fh:
        while True:
            if is_cancelled and is_cancelled():
                raise YouTubeError("Envio cancelado", "cancelled")
            fh.seek(offset)
            chunk = fh.read(CHUNK)
            end = offset + len(chunk) - 1
            status_, headers, body = _request(
                "PUT", session_url, data=chunk,
                headers={"Authorization": f"Bearer {access_token()}", "Content-Length": str(len(chunk)),
                         "Content-Range": f"bytes {offset}-{end}/{size}" if chunk else f"bytes */{size}"})
            if status_ in (200, 201):
                if on_progress:
                    on_progress(size, size)
                return _json(body)
            if status_ == 308:
                new = _confirmed_bytes(headers)
                stalls = stalls + 1 if new <= offset else 0
                if stalls >= 3:
                    raise YouTubeError("O YouTube não está aceitando as partes do vídeo", "retry", status_)
                offset = new
                if on_progress:
                    on_progress(offset, size)
                continue
            if status_ in (404, 410):
                raise YouTubeError("A sessão de envio expirou; começando de novo", "restart", status_)
            raise _api_error(status_, body)
