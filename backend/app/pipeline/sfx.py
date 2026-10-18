"""Efeitos sonoros discretos, sintetizados pelo próprio app (sem arquivos de terceiros).

Monta uma única faixa (WAV) do tamanho do vídeo com os efeitos nos instantes certos, que o
FFmpeg mistura por baixo da fala:
- "whoosh": passagem de ar na transição depois do gancho;
- "pop": estalo leve quando o título aparece;
- "bip": tom de 1 kHz por cima de palavrões (modo "bip").
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
LEVELS = {"sutil": 0.16, "normal": 0.3}  # pico do whoosh/pop (fala normalizada fica perto de 0.8)
BIP_GAIN = 0.22


def _env(n: int, attack: float) -> np.ndarray:
    """Envelope que sobe até `attack` (fração) e desce suave."""
    x = np.linspace(0, 1, n, endpoint=False)
    up = np.clip(x / attack, 0, 1) ** 2
    down = np.clip((1 - x) / (1 - attack), 0, 1) ** 1.5
    return up * down


def whoosh(dur: float = 0.5, seed: int = 7) -> np.ndarray:
    """Ruído filtrado com corte que abre e fecha: soa como uma passagem de ar."""
    n = int(dur * SR)
    noise = np.random.default_rng(seed).standard_normal(n)
    env = _env(n, 0.62)
    # passa-baixas de 1 polo com frequência variando junto com o envelope (300 Hz → 5 kHz)
    fc = 300 + 4700 * env
    alpha = 1 - np.exp(-2 * np.pi * fc / SR)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):  # 24 mil amostras: rápido o bastante em Python puro
        acc += alpha[i] * (noise[i] - acc)
        out[i] = acc
    out *= env
    return out / (np.abs(out).max() or 1)


def pop(dur: float = 0.09) -> np.ndarray:
    """Estalo curto: senoide caindo de 900 para 250 Hz com decaimento rápido."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    freq = 250 + 650 * np.exp(-t / 0.018)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    out = np.sin(phase) * np.exp(-t / 0.025)
    out[: int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))
    return out / np.abs(out).max()


def bip(dur: float) -> np.ndarray:
    n = max(int(dur * SR), 1)
    t = np.arange(n) / SR
    out = np.sin(2 * np.pi * 1000 * t)
    ramp = min(int(0.005 * SR), n // 2)
    if ramp:
        out[:ramp] *= np.linspace(0, 1, ramp)
        out[-ramp:] *= np.linspace(1, 0, ramp)
    return out


def build_track(duration: float, path: Path, level: str | None, whoosh_at: float | None = None,
                pop_at: list[float] | None = None, bips: list[tuple[float, float]] | None = None) -> Path | None:
    """Gera a faixa de efeitos. None se não houver nenhum efeito a tocar."""
    gain = LEVELS.get(level or "", 0.0)
    track = np.zeros(int((duration + 0.5) * SR))

    def place(sig: np.ndarray, at: float, g: float) -> None:
        i = max(int(at * SR), 0)
        j = min(i + len(sig), len(track))
        if j > i:
            track[i:j] += sig[: j - i] * g

    placed = False
    if gain and whoosh_at is not None:
        w = whoosh()
        place(w, whoosh_at - 0.62 * len(w) / SR, gain)  # pico do whoosh exatamente na transição
        placed = True
    if gain:
        for t in pop_at or []:
            place(pop(), t, gain * 0.8)
            placed = True
    for a, b in bips or []:
        place(bip(b - a), a, BIP_GAIN)
        placed = True
    if not placed:
        return None
    pcm = (np.clip(track, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return path
