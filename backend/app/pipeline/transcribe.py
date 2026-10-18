"""Transcrição com timestamps por palavra.

Motores:
- faster-whisper (local, padrão). Os timestamps por palavra vêm do alinhamento
  por atenção cruzada (DTW) do próprio Whisper (`word_timestamps=True`), e o VAD
  Silero remove trechos de silêncio antes da transcrição.
- Importação de legenda existente (.srt/.vtt). Útil quando você já tem a legenda
  do seu vídeo ou em computadores sem recursos para o Whisper. Os tempos por
  palavra são estimados proporcionalmente dentro de cada bloco da legenda.

Formato interno (JSON):
    {"engine": str, "language": str, "duration": float,
     "segments": [{"start", "end", "text", "words": [{"text", "start", "end", "prob"}]}]}
"""
from __future__ import annotations

import json
import re
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pysubs2

from .. import config
from .context import JobContext
from .errors import FatalPipelineError, PipelineError

_model_lock = threading.Lock()
_model_cache: dict[tuple, Any] = {}


def whisper_available() -> dict:
    try:
        import faster_whisper  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    model = config.get("transcription.model")
    cache_dir = models_dir()
    cached = any(cache_dir.glob(f"**/*faster-whisper-{model}*")) if cache_dir.exists() else False
    return {"installed": installed, "model": model, "model_cached": bool(cached), "cache_dir": str(cache_dir)}


def models_dir() -> Path:
    d = config.data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_model(model_name: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise FatalPipelineError(
            "faster-whisper não está instalado. Rode: pip install faster-whisper "
            "(ou envie uma legenda .srt junto com o vídeo)."
        ) from exc
    key = (model_name, device, compute_type)
    with _model_lock:
        if key not in _model_cache:
            _model_cache.clear()  # mantém apenas um modelo em memória
            try:
                _model_cache[key] = WhisperModel(
                    model_name, device=device, compute_type=compute_type,
                    download_root=str(models_dir()),
                )
            except Exception as exc:  # download/rede/memória
                raise PipelineError(
                    f"Não foi possível carregar o modelo Whisper '{model_name}': {exc}. "
                    "Na primeira execução o modelo é baixado do Hugging Face (precisa de internet). "
                    "Em computadores com pouca RAM use o modelo 'base' ou 'tiny' nas Configurações."
                ) from exc
        return _model_cache[key]


def load_wav(path: Path) -> np.ndarray:
    """Lê o WAV mono 16 kHz (extraído pelo FFmpeg) como float32, o formato que o Whisper espera.

    Passar o áudio já decodificado evita o decodificador interno do faster-whisper (PyAV),
    que quebra com algumas versões novas do PyAV ("unexpected keyword argument 'metadata_errors'").
    """
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise PipelineError("Áudio de análise em formato inesperado (esperado WAV 16 kHz, 16 bits)")
        channels = wf.getnchannels()
        out = np.empty(wf.getnframes(), dtype=np.float32)
        pos = 0
        while True:  # em blocos, para não duplicar a memória em episódios longos
            raw = wf.readframes(16000 * 60)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16)
            if channels > 1:
                x = x.reshape(-1, channels).mean(axis=1)
            out[pos:pos + len(x)] = x / 32768.0
            pos += len(x)
    return out[:pos]


def transcribe_whisper(audio_path: Path, duration: float, ctx: JobContext) -> dict:
    model_name = config.get("transcription.model")
    device = config.get("transcription.device")
    compute_type = config.get("transcription.compute_type")
    language = config.get("transcription.language") or None
    ctx.log.info("Carregando modelo Whisper %s (%s/%s)", model_name, device, compute_type)
    model = _load_model(model_name, device, compute_type)
    ctx.check()
    segments_iter, info = model.transcribe(
        load_wav(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=bool(config.get("transcription.vad_filter")),
        vad_parameters={"min_silence_duration_ms": 700},
        beam_size=5,
        condition_on_previous_text=False,
    )
    total = duration or getattr(info, "duration", 0) or 1.0
    segments: list[dict] = []
    for seg in segments_iter:
        ctx.check()
        ctx.progress(seg.end / total)
        if getattr(seg, "no_speech_prob", 0) > 0.7 and getattr(seg, "avg_logprob", 0) < -1.0:
            continue  # provável alucinação em trecho sem fala
        words = [
            {"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
             "prob": round(float(w.probability), 3)}
            for w in (seg.words or []) if w.word.strip()
        ]
        if not words:
            continue
        segments.append({"start": words[0]["start"], "end": words[-1]["end"],
                         "text": seg.text.strip(), "words": words})
    ctx.progress(1.0)
    return {"engine": f"faster-whisper:{model_name}", "language": getattr(info, "language", language or ""),
            "duration": total, "segments": _drop_repetitions(segments)}


def _drop_repetitions(segments: list[dict]) -> list[dict]:
    """Remove repetições em sequência (alucinação clássica do Whisper em silêncio/música)."""
    out: list[dict] = []
    repeat = 0
    for seg in segments:
        if out and seg["text"].strip().lower() == out[-1]["text"].strip().lower():
            repeat += 1
            if repeat >= 2:
                continue
        else:
            repeat = 0
        out.append(seg)
    return out


_TAG_RE = re.compile(r"<[^>]+>|\{[^}]*\}")


def _split_words(text: str, start: float, end: float) -> list[dict]:
    tokens = [t for t in re.split(r"\s+", text) if t]
    if not tokens or end <= start:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    span = end - start
    words, t = [], start
    for tok, w in zip(tokens, weights):
        d = span * w / total
        words.append({"text": tok, "start": round(t, 3), "end": round(t + d * 0.92, 3), "prob": None})
        t += d
    words[-1]["end"] = round(end, 3)
    return words


def import_subtitles(sub_path: Path, duration: float) -> dict:
    try:
        subs = pysubs2.load(str(sub_path), encoding="utf-8")
    except Exception as exc:
        raise FatalPipelineError(f"Não foi possível ler a legenda enviada: {exc}") from exc
    segments = []
    for ev in subs:
        if ev.is_comment:
            continue
        text = _TAG_RE.sub("", ev.plaintext).replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        s, e = ev.start / 1000.0, ev.end / 1000.0
        if duration:
            e = min(e, duration)
        words = _split_words(text, s, e)
        if words:
            segments.append({"start": s, "end": e, "text": text, "words": words})
    if not segments:
        raise FatalPipelineError("A legenda enviada está vazia")
    segments.sort(key=lambda x: x["start"])
    return {"engine": "subtitle-import", "language": config.get("transcription.language"),
            "duration": duration, "segments": segments}


def all_words(transcript: dict) -> list[dict]:
    return [w for seg in transcript["segments"] for w in seg["words"]]


def to_srt(segments: list[dict], path: Path, offset: float = 0.0) -> Path:
    subs = pysubs2.SSAFile()
    for seg in segments:
        subs.append(pysubs2.SSAEvent(start=int(max(seg["start"] - offset, 0) * 1000),
                                     end=int(max(seg["end"] - offset, 0) * 1000), text=seg["text"]))
    subs.save(str(path), format_="srt")
    return path


def save(transcript: dict, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
