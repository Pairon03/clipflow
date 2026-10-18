"""Gera mídia de teste com conteúdo conhecido (rostos, fala e legenda com tempos exatos)."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SENTENCES = [
    "Você sabia que o segredo para aprender qualquer coisa é a repetição espaçada?",
    "Quando eu comecei a estudar programação, eu não sabia nada.",
    "Um dia eu descobri um método simples que mudou minha vida.",
    "O método funciona assim: você revisa o conteúdo em intervalos cada vez maiores.",
    "Por isso a memória de longo prazo fica muito mais forte.",
    "E aí, tipo, isso que você falou antes também.",
    "Na minha opinião, todo mundo deveria aprender isso na escola.",
    "A diferença entre quem aprende rápido e quem não aprende é a constância.",
    "Qual foi o maior erro que você cometeu no começo?",
    "O maior erro foi tentar estudar tudo de uma vez, sem descanso nenhum.",
    "Hoje eu estudo trinta minutos por dia e aprendo muito mais.",
    "Essa é a dica mais importante que eu posso dar para você.",
]


def _tts(text: str, out: Path, sr: int = 16000) -> float:
    if shutil.which("espeak-ng"):
        raw = out.with_suffix(".raw.wav")
        subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "165", "-w", str(raw), text], check=True,
                       capture_output=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar", str(sr), str(out)],
                       check=True)
        raw.unlink()
    else:  # sem TTS: "fala" sintética (tons modulados) com duração proporcional ao texto
        dur = 0.075 * len(text)
        t = np.arange(int(sr * dur)) / sr
        sig = 0.3 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes((sig * 32767).astype(np.int16).tobytes())
    with wave.open(str(out), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def speech_track(work: Path, gaps: list[float] | None = None, repeat: int = 1) -> tuple[Path, Path, list]:
    """Cria WAV com as frases + SRT com tempos exatos. Retorna (wav, srt, [(start,end,text)])."""
    work.mkdir(parents=True, exist_ok=True)
    sr = 16000
    pieces: list[np.ndarray] = []
    cues = []
    t = 0.6
    pieces.append(np.zeros(int(sr * 0.6), dtype=np.int16))
    sentences = SENTENCES * repeat
    for i, text in enumerate(sentences):
        f = work / f"s{i}.wav"
        dur = _tts(text, f, sr)
        with wave.open(str(f), "rb") as wf:
            pieces.append(np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16))
        f.unlink()
        cues.append((t, t + dur, text))
        gap = (gaps[i % len(gaps)] if gaps else (1.6 if i % 4 == 3 else 0.5))
        t += dur + gap
        pieces.append(np.zeros(int(sr * gap), dtype=np.int16))
    wav = work / "speech.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(np.concatenate(pieces).tobytes())
    srt = work / "speech.srt"
    srt.write_text("\n".join(f"{i + 1}\n{_srt_time(a)} --> {_srt_time(b)}\n{txt}\n"
                             for i, (a, b, txt) in enumerate(cues)), encoding="utf-8")
    return wav, srt, cues


def face_image(size: int = 260) -> np.ndarray:
    import cv2
    from skimage import data

    img = data.astronaut()[20:300, 120:400, ::-1]  # recorte em torno do rosto, BGR
    return cv2.resize(np.ascontiguousarray(img), (size, size))


def make_video(out: Path, audio: Path, duration: float, mode: str = "two", w: int = 1280, h: int = 720,
               fps: int = 12) -> Path:
    """mode: 'two' (dois rostos fixos), 'moving' (um rosto se move), 'none' (sem rostos)."""
    face = face_image(int(h * 0.42)) if mode != "none" else None
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "pipe:0", "-i", str(audio), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(duration * fps)
    base = np.zeros((h, w, 3), np.uint8)
    base[:] = (38, 30, 28)
    base[int(h * 0.75):] = (60, 45, 40)
    for i in range(n):
        frame = base.copy()
        if face is not None:
            fs = face.shape[0]
            y = int(h * 0.18)
            if mode == "two":
                for x in (int(w * 0.22) - fs // 2, int(w * 0.78) - fs // 2):
                    frame[y:y + fs, x:x + fs] = face
            elif mode == "moving":
                prog = i / max(n - 1, 1)
                cx = int(w * (0.25 + 0.5 * prog))
                x = cx - fs // 2
                frame[y:y + fs, x:x + fs] = face
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("falha ao gerar vídeo de teste")
    return out


def build_sample(work: Path, mode: str = "two", repeat: int = 1) -> dict:
    wav, srt, cues = speech_track(work, repeat=repeat)
    with wave.open(str(wav), "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
    video = make_video(work / f"sample_{mode}.mp4", wav, dur, mode=mode)
    return {"video": video, "srt": srt, "cues": cues, "duration": dur}
