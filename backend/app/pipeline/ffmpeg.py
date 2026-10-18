"""Wrappers seguros para FFmpeg/FFprobe.

Os comandos são sempre montados como listas de argumentos (nunca via shell),
o que impede execução arbitrária de comandos a partir de nomes de arquivo ou URLs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from .context import JobContext
from .errors import Cancelled, FatalPipelineError, PipelineError

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _find(name: str) -> str | None:
    env = os.environ.get(f"CLIPFLOW_{name.upper()}")
    if env and Path(env).is_file():
        return env
    exe = name + (".exe" if sys.platform == "win32" else "")
    local = config.PROJECT_ROOT / "bin" / exe
    if local.is_file():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        # o winget instala aqui, mas o PATH só é atualizado em processos abertos depois da instalação
        roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"]
        for links in (roots[0] / "Links" / exe,):
            if links.is_file():
                return str(links)
        for pattern in ("Packages/Gyan.FFmpeg*/*/bin/" + exe, "Packages/BtbN.FFmpeg*/*/bin/" + exe):
            for hit in sorted(roots[0].glob(pattern), reverse=True):
                return str(hit)
        for extra in (Path("C:/ffmpeg/bin") / exe, Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ffmpeg" / "bin" / exe):
            if extra.is_file():
                return str(extra)
    return None


def ffmpeg_bin() -> str:
    p = _find("ffmpeg")
    if not p:
        raise FatalPipelineError(
            "FFmpeg não encontrado. No Windows, abra o PowerShell e rode: winget install Gyan.FFmpeg — depois "
            "feche e abra de novo o start-windows.bat (ou reinicie o PC). Alternativa: copie ffmpeg.exe e "
            "ffprobe.exe para a pasta bin do ClipFlow."
        )
    return p


def ffprobe_bin() -> str:
    p = _find("ffprobe")
    if not p:
        raise FatalPipelineError(
            "FFprobe não encontrado. Ele acompanha o FFmpeg; verifique a instalação."
        )
    return p


def available() -> dict:
    out = {"ffmpeg": _find("ffmpeg"), "ffprobe": _find("ffprobe"), "version": None, "libass": False}
    if out["ffmpeg"]:
        try:
            r = subprocess.run([out["ffmpeg"], "-hide_banner", "-version"], capture_output=True,
                               text=True, timeout=15, creationflags=_CREATE_NO_WINDOW)
            out["version"] = r.stdout.splitlines()[0] if r.stdout else None
            r = subprocess.run([out["ffmpeg"], "-hide_banner", "-filters"], capture_output=True,
                               text=True, timeout=15, creationflags=_CREATE_NO_WINDOW)
            out["libass"] = " ass " in r.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return out


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    audio_codec: str | None
    size: int
    format_name: str
    rotation: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "raw"}


def _parse_fps(rate: str | None) -> float:
    if not rate or rate in {"0/0", "0"}:
        return 0.0
    if "/" in rate:
        n, d = rate.split("/", 1)
        try:
            return float(n) / float(d) if float(d) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe(path: Path | str) -> MediaInfo:
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise FatalPipelineError("Tempo esgotado ao ler o arquivo de vídeo") from exc
    if r.returncode != 0:
        raise FatalPipelineError("Arquivo de vídeo inválido ou corrompido: " + (r.stderr.strip()[:300] or "erro"))
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise FatalPipelineError("O arquivo não contém trilha de vídeo")
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or v.get("duration") or 0)
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    if "rotate" in (v.get("tags") or {}):
        rotation = int(v["tags"]["rotate"])
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return MediaInfo(
        duration=duration,
        width=w,
        height=h,
        fps=_parse_fps(v.get("avg_frame_rate")) or _parse_fps(v.get("r_frame_rate")),
        has_audio=a is not None,
        video_codec=v.get("codec_name", ""),
        audio_codec=a.get("codec_name") if a else None,
        size=int(fmt.get("size") or Path(path).stat().st_size),
        format_name=fmt.get("format_name", ""),
        rotation=rotation,
        raw=data,
    )


def run(
    args: list[str],
    ctx: JobContext | None = None,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    timeout: float | None = None,
) -> str:
    """Executa o ffmpeg com acompanhamento real de progresso (-progress pipe:1).

    Retorna o stderr (útil para filtros de análise como silencedetect).
    """
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    err_file = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, creationflags=_CREATE_NO_WINDOW)
    if ctx:
        ctx.register(proc)
    stop = threading.Event()
    started = time.monotonic()

    def watchdog() -> None:
        while not stop.wait(0.5):
            if ctx and ctx.cancelled():
                proc.kill()
                return
            if timeout and time.monotonic() - started > timeout:
                proc.kill()
                return

    t = threading.Thread(target=watchdog, daemon=True)
    t.start()
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if on_progress and duration and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(us / 1e6 / duration, 1.0))
                except ValueError:
                    pass
        proc.wait()
    finally:
        stop.set()
        if ctx:
            ctx.unregister(proc)
    err_file.seek(0)
    stderr = err_file.read().decode("utf-8", "replace")
    err_file.close()
    if ctx and ctx.cancelled():
        raise Cancelled()
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-8:])
        if timeout and time.monotonic() - started > timeout:
            raise PipelineError("FFmpeg excedeu o tempo limite")
        raise PipelineError(f"FFmpeg falhou (código {proc.returncode}): {tail[-800:]}")
    if on_progress:
        on_progress(1.0)
    return stderr


def extract_audio(src: Path, dst: Path, ctx: JobContext | None = None, duration: float | None = None,
                  on_progress: Callable[[float], None] | None = None) -> Path:
    """Extrai áudio mono 16 kHz (formato ideal para Whisper e análise)."""
    run(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        ctx=ctx, duration=duration, on_progress=on_progress)
    return dst


def thumbnail(src: Path, dst: Path, at: float, width: int = 360) -> Path:
    run(["-ss", f"{max(at, 0):.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2",
         "-q:v", "4", str(dst)], timeout=60)
    return dst


def verify_output(path: Path, expected_duration: float | None, width: int, height: int,
                  decode: bool = True, ctx: JobContext | None = None) -> dict:
    """Confere integridade do MP4 final. Lança PipelineError se algo estiver errado."""
    if not path.is_file() or path.stat().st_size < 1024:
        raise PipelineError("Arquivo exportado ausente ou vazio")
    info = probe(path)
    problems = []
    if info.video_codec != "h264":
        problems.append(f"codec de vídeo {info.video_codec} (esperado h264)")
    if (info.width, info.height) != (width, height):
        problems.append(f"resolução {info.width}x{info.height} (esperado {width}x{height})")
    if not info.has_audio or info.audio_codec != "aac":
        problems.append("áudio AAC ausente")
    if expected_duration and abs(info.duration - expected_duration) > max(0.6, expected_duration * 0.03):
        problems.append(f"duração {info.duration:.2f}s (esperado {expected_duration:.2f}s)")
    if decode:
        try:
            run(["-v", "error", "-i", str(path), "-f", "null", "-"], ctx=ctx, timeout=600)
        except PipelineError as exc:
            problems.append(f"falha ao decodificar: {exc}")
    if problems:
        raise PipelineError("Verificação de integridade falhou: " + "; ".join(problems))
    return info.as_dict()
