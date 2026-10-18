"""Análise de áudio leve (sem bibliotecas pesadas): energia por janela e clipping."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

WINDOW_S = 0.1


def energy_profile(wav_path: Path) -> dict:
    """Lê o WAV mono 16-bit em blocos e calcula RMS (dBFS) e clipping por janela de 100 ms."""
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("WAV precisa ser 16-bit")
        sr = wf.getframerate()
        ch = wf.getnchannels()
        win = int(sr * WINDOW_S)
        rms_db: list[np.ndarray] = []
        clip: list[np.ndarray] = []
        block = win * 600  # ~60 s por leitura
        while True:
            raw = wf.readframes(block)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16)
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            n = len(x) // win
            if n == 0:
                break
            x = x[: n * win].astype(np.float32).reshape(n, win) / 32768.0
            r = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
            rms_db.append(20 * np.log10(r))
            clip.append(np.mean(np.abs(x) > 0.985, axis=1))
    if not rms_db:
        return {"window": WINDOW_S, "rms_db": np.zeros(0), "clip": np.zeros(0)}
    return {"window": WINDOW_S, "rms_db": np.concatenate(rms_db), "clip": np.concatenate(clip)}


def segment_quality(profile: dict, start: float, end: float) -> float:
    """Nota 0–1 para a qualidade do áudio no intervalo (volume adequado, pouco clipping, pouco silêncio)."""
    rms = profile["rms_db"]
    if rms is None or len(rms) == 0:
        return 0.7
    w = profile["window"]
    a, b = int(start / w), max(int(end / w), int(start / w) + 1)
    seg = rms[a:b]
    if len(seg) == 0:
        return 0.5
    voiced = seg[seg > -45]
    voiced_ratio = len(voiced) / len(seg)
    level = float(np.median(voiced)) if len(voiced) else -60.0
    # nível ideal de fala entre -30 e -12 dBFS
    if -30 <= level <= -12:
        level_score = 1.0
    elif level < -30:
        level_score = max(0.0, 1 - (-30 - level) / 20)
    else:
        level_score = max(0.0, 1 - (level + 12) / 10)
    clip_ratio = float(np.mean(profile["clip"][a:b])) if len(profile["clip"]) else 0.0
    clip_score = max(0.0, 1 - clip_ratio * 200)
    voiced_score = min(1.0, voiced_ratio / 0.75)
    return round(0.45 * level_score + 0.25 * clip_score + 0.30 * voiced_score, 3)
