"""Ponte com o Concat (editor de vídeo open source, https://github.com/jub0t/Concat).

O ClipFlow não incorpora código do Concat (licença AGPL-3.0): ele executa o programa
instalado como um processo separado (`concat --mcp headless`) e conversa com ele pelo
protocolo MCP (JSON-RPC 2.0, uma mensagem por linha no stdin/stdout).

Uso: para um Short já analisado, o ClipFlow renderiza uma versão sem legenda queimada,
cria um projeto do Concat em 1080×1920 com esse vídeo e coloca as legendas como títulos
editáveis. O usuário abre o projeto no Concat para ajustes finos (efeitos, textos,
transições) e exporta por lá.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .. import config
from .errors import FatalPipelineError, PipelineError
from .ffmpeg import _CREATE_NO_WINDOW

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_S = 120


def _candidates() -> list[Path]:
    out: list[Path] = []
    configured = config.get("concat.path")
    if configured:
        out.append(Path(configured))
    if os.environ.get("CLIPFLOW_CONCAT"):
        out.append(Path(os.environ["CLIPFLOW_CONCAT"]))
    exe = ".exe" if sys.platform == "win32" else ""
    out.append(config.PROJECT_ROOT / "bin" / f"concat{exe}")
    out.append(config.PROJECT_ROOT / "bin" / f"concat-mcp{exe}")
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            out.append(Path(local) / "Programs" / "Concat" / "concat.exe")
        out.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Concat" / "concat.exe")
    elif sys.platform == "darwin":
        out.append(Path("/Applications/Concat.app/Contents/MacOS/concat"))
    else:
        out.append(Path("/usr/bin/concat"))
    for name in ("concat", "concat-mcp"):
        found = shutil.which(name)
        if found:
            out.append(Path(found))
    return out


def valid_executable(path: Path) -> bool:
    """Só aceita executáveis cujo nome comece com 'concat' (evita apontar para outro programa)."""
    return path.is_file() and path.name.lower().startswith("concat")


def find_executable() -> Path | None:
    for p in _candidates():
        if valid_executable(p):
            return p
    return None


def command(exe: Path) -> list[str]:
    # o binário de desenvolvimento `concat-mcp` recebe o modo direto; o app recebe `--mcp <modo>`
    if exe.stem.lower().startswith("concat-mcp"):
        return [str(exe), "headless"]
    return [str(exe), "--mcp", "headless"]


class McpError(PipelineError):
    pass


class ConcatClient:
    """Cliente MCP mínimo sobre stdio, com tempo limite por chamada."""

    def __init__(self, exe: Path, roots: list[Path]):
        env = os.environ.copy()
        env["CONCAT_MCP_ROOTS"] = os.pathsep.join(str(r) for r in roots)
        self.proc = subprocess.Popen(
            command(exe), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, creationflags=_CREATE_NO_WINDOW,
        )
        self._lines: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._next_id = 0

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            self._lines.put(raw.decode("utf-8", "replace"))
        self._lines.put(None)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            self._stderr.append(raw.decode("utf-8", "replace").rstrip())
            del self._stderr[:-50]

    def _send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(message) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None, timeout: float = TIMEOUT_S) -> dict:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty as exc:
                raise McpError(f"O Concat não respondeu a '{method}' em {timeout:.0f}s") from exc
            if line is None:
                tail = " | ".join(self._stderr[-5:])
                raise McpError(f"O Concat encerrou inesperadamente. {tail}".strip())
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") != rid:
                continue  # notificações (ex.: progresso)
            if "error" in msg:
                raise McpError(f"Concat: {msg['error'].get('message', msg['error'])}")
            return msg.get("result", {})

    def initialize(self) -> dict:
        res = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "clipflow-studio", "version": "0.1.0"},
        }, timeout=60)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def call(self, tool: str, arguments: dict, timeout: float = TIMEOUT_S) -> dict:
        res = self.request("tools/call", {"name": tool, "arguments": arguments}, timeout=timeout)
        text = " ".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise McpError(f"Concat recusou '{tool}': {text[:400]}")
        if isinstance(res.get("structuredContent"), dict):
            return res["structuredContent"]
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {"value": data}
        except ValueError:
            return {"text": text}

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()

    def __enter__(self) -> "ConcatClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def status() -> dict:
    exe = find_executable()
    out = {"available": bool(exe), "path": str(exe) if exe else None, "version": None}
    if exe:
        try:
            with ConcatClient(exe, [config.data_dir()]) as c:
                c.initialize()
                out["version"] = c.call("concat_version", {}, timeout=30)
        except PipelineError as exc:
            out["error"] = str(exc)
    return out


# ------------------------------------------------------------------ montagem do projeto
CAPTION_FONTS = {
    "classic": ("Montserrat", 800),
    "neon": ("Montserrat", 800),
    "minimal": ("Inter", 700),
    "impact": ("Anton", 400),
}


def caption_entries(words: list[dict], caption_style: str) -> list[dict]:
    """Agrupa as palavras (já no tempo do vídeo final) em blocos curtos e editáveis."""
    from . import subtitles

    st = subtitles.resolve_style(caption_style)
    entries = []
    for g in subtitles.group_words(words, st.max_chars, st.max_words):
        text = " ".join(w["text"] for w in g)
        start, end = round(g[0]["start"], 3), round(g[-1]["end"] + 0.12, 3)
        if end <= start:
            end = start + 0.3
        entries.append({"start": start, "end": end, "text": text.upper() if st.uppercase else text})
    # sem sobreposição entre blocos
    for a, b in zip(entries, entries[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + 0.05, b["start"])
    return entries


def build_project(exe: Path, location: Path, name: str, video: Path, words: list[dict],
                  caption_style: str, fps: int, width: int, height: int) -> Path:
    """Cria (ou recria) o projeto do Concat em `location/name`. Retorna a pasta do projeto."""
    location.mkdir(parents=True, exist_ok=True)
    project_dir = location / name
    if project_dir.exists():
        shutil.rmtree(project_dir)  # pasta gerada pelo próprio ClipFlow; recriada do zero
    font, weight = CAPTION_FONTS.get(caption_style, CAPTION_FONTS["classic"])
    with ConcatClient(exe, [config.data_dir()]) as c:
        c.initialize()
        c.call("project_create", {"location": str(location), "name": name,
                                  "video": {"width": width, "height": height, "rateNum": int(fps), "rateDen": 1}})
        path = str(project_dir)
        media = c.call("media_import", {"path": path, "file": str(video)})
        media_id = media.get("createdId")
        if not media_id:
            raise McpError("O Concat não devolveu o id da mídia importada")
        c.call("clips_add_sequence", {"path": path, "mediaIds": [media_id], "start": 0.0})
        entries = caption_entries(words, caption_style)
        if entries:
            c.call("captions_add", {"path": path, "captions": entries, "offsetY": 0.2,
                                    "style": {"fontFamily": font, "fontWeight": weight, "fontSize": 0.045,
                                              "color": "#ffffff", "strokeWidth": 0.003,  # fração da altura (~6 px)
                                              "strokeColor": "#000000"}})
        c.call("project_save", {"path": path})
        c.call("project_close", {"path": path, "save": False})
    if not project_dir.is_dir():
        raise McpError("O Concat terminou sem criar a pasta do projeto")
    return project_dir


def open_in_editor(project_dir: Path) -> None:
    """Abre o projeto na janela do Concat (o app desktop precisa estar instalado)."""
    exe = find_executable()
    if not exe or exe.stem.lower().startswith("concat-mcp"):
        raise FatalPipelineError("Concat (app desktop) não encontrado. Instale em https://concatenate.pages.dev")
    subprocess.Popen([str(exe), "--project", str(project_dir)], creationflags=_CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
