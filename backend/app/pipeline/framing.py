"""Enquadramento inteligente para 9:16.

- Amostra quadros do trecho (ffmpeg → numpy), detecta rostos com MediaPipe
  (BlazeFace) e usa OpenCV Haar como alternativa.
- Associa detecções no tempo (rastreamento simples por proximidade) e descarta
  detecções esporádicas (falsos positivos).
- Gera o caminho da "câmera virtual" com zona morta + suavização + limite de
  velocidade, para o enquadramento não ficar tremendo.
- Layouts: follow (segue o rosto principal), speaker (alterna para quem está
  falando, por movimento da boca — experimental), split (dois rostos empilhados),
  fit (quadro inteiro sobre fundo desfocado), center (corte central) e manual.
"""
from __future__ import annotations

import atexit
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import config
from .context import JobContext
from .ffmpeg import _CREATE_NO_WINDOW, ffmpeg_bin

log = logging.getLogger("clipflow.framing")

ANALYSIS_W = 640
SAMPLE_FPS = 6.0
LAYOUTS = {"auto", "follow", "speaker", "split", "fit", "center", "manual"}


# ---------------------------------------------------------------- detecção
class FaceDetector:
    """Detector com MediaPipe (preferido) e Haar cascade (alternativa)."""

    _lock = threading.Lock()

    def __init__(self) -> None:
        self.kind = None
        self._mp = None
        self._haar = None
        model = config.MODELS_DIR / "blaze_face_short_range.tflite"
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_tasks
            from mediapipe.tasks.python import vision

            opts = vision.FaceDetectorOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=str(model)),
                min_detection_confidence=0.5,
            )
            self._mp = vision.FaceDetector.create_from_options(opts)
            self._mp_mod = mp
            self.kind = "mediapipe"
            # fecha antes do executor interno do MediaPipe ser desligado no fim do processo
            register = getattr(threading, "_register_atexit", atexit.register)
            register(self.close)
        except Exception as exc:  # mediapipe ausente ou incompatível
            log.info("MediaPipe indisponível (%s); usando OpenCV Haar", exc)
        try:
            import cv2

            haar = config.MODELS_DIR / "haarcascade_frontalface_default.xml"
            c = cv2.CascadeClassifier(str(haar))
            if not c.empty():
                self._haar = c
                self.kind = self.kind or "haar"
        except Exception as exc:
            log.warning("OpenCV indisponível: %s", exc)

    def close(self) -> None:
        if self._mp is not None:
            try:
                self._mp.close()
            except Exception:
                pass
            self._mp = None

    @property
    def available(self) -> bool:
        return self.kind is not None

    def _detect_mp(self, rgb: np.ndarray) -> list[tuple]:
        img = self._mp_mod.Image(image_format=self._mp_mod.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._mp.detect(img)
        out = []
        for d in res.detections:
            b = d.bounding_box
            out.append((b.origin_x, b.origin_y, b.width, b.height, d.categories[0].score if d.categories else 0.5))
        return out

    def detect(self, bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """Retorna rostos como (cx, cy, w, h, score) normalizados 0–1."""
        h, w = bgr.shape[:2]
        boxes: list[tuple] = []
        if self._mp is not None:
            rgb = bgr[:, :, ::-1]
            with self._lock:
                boxes += self._detect_mp(rgb)
                # rostos pequenos (planos abertos): detecta também em metades sobrepostas
                if w > h * 1.2:
                    half = int(w * 0.6)
                    for x0 in (0, w - half):
                        for (bx, by, bw, bh, s) in self._detect_mp(rgb[:, x0:x0 + half]):
                            boxes.append((bx + x0, by, bw, bh, s))
        if not boxes and self._haar is not None:
            import cv2

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            for (bx, by, bw, bh) in self._haar.detectMultiScale(gray, 1.1, 6, minSize=(max(20, h // 18),) * 2):
                boxes.append((bx, by, bw, bh, 0.6))
        boxes = _nms(boxes)
        return [((bx + bw / 2) / w, (by + bh / 2) / h, bw / w, bh / h, s) for (bx, by, bw, bh, s) in boxes]


def _nms(boxes: list[tuple], thr: float = 0.4) -> list[tuple]:
    boxes = sorted(boxes, key=lambda b: -b[4])
    keep: list[tuple] = []
    for b in boxes:
        if all(_iou(b, k) < thr for k in keep):
            keep.append(b)
    return keep


def _iou(a: tuple, b: tuple) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


_detector: FaceDetector | None = None
_detector_lock = threading.Lock()


def get_detector() -> FaceDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = FaceDetector()
        return _detector


# ---------------------------------------------------------------- amostragem
def sample_frames(src: Path, start: float, duration: float, src_w: int, src_h: int,
                  fps: float = SAMPLE_FPS, ctx: JobContext | None = None):
    """Gera (t_relativo, frame_bgr) usando ffmpeg com saída rawvideo (sem arquivos temporários)."""
    aw = ANALYSIS_W if src_w > ANALYSIS_W else src_w - (src_w % 2)
    ah = int(round(src_h * aw / src_w / 2) * 2)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
           "-i", str(src), "-an", "-vf", f"fps={fps},scale={aw}:{ah}", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
    if ctx:
        ctx.register(proc)
    size = aw * ah * 3
    i = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i / fps, np.frombuffer(buf, dtype=np.uint8).reshape(ah, aw, 3)
            i += 1
            if ctx and ctx.cancelled():
                break
    finally:
        proc.kill()
        proc.wait()
        if ctx:
            ctx.unregister(proc)


# ---------------------------------------------------------------- rastreamento
@dataclass
class Track:
    points: list[tuple] = field(default_factory=list)  # (t, cx, cy, w, h)
    motion: dict = field(default_factory=dict)          # t -> energia de movimento da boca

    @property
    def last(self) -> tuple:
        return self.points[-1]

    def median(self) -> tuple[float, float, float, float]:
        a = np.array([p[1:] for p in self.points])
        return tuple(float(x) for x in np.median(a, axis=0))  # cx, cy, w, h


def _track(samples: list[tuple[float, list]], max_dist: float = 0.12) -> list[Track]:
    tracks: list[Track] = []
    for t, faces in samples:
        used = set()
        for f in sorted(faces, key=lambda f: -f[2] * f[3]):
            best, best_d = None, max_dist
            for k, tr in enumerate(tracks):
                if k in used or t - tr.last[0] > 2.0:
                    continue
                d = ((tr.last[1] - f[0]) ** 2 + (tr.last[2] - f[1]) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = k, d
            if best is None:
                tracks.append(Track([(t, f[0], f[1], f[2], f[3])], {t: f[4]}))
                used.add(len(tracks) - 1)
            else:
                tracks[best].points.append((t, f[0], f[1], f[2], f[3]))
                tracks[best].motion[t] = f[4]
                used.add(best)
    return tracks


def _merge_tracks(tracks: list[Track], max_dist: float = 0.1) -> list[Track]:
    """Junta trilhas da mesma pessoa que foram separadas por falhas de detecção."""
    tracks = sorted(tracks, key=lambda tr: -len(tr.points))
    merged: list[Track] = []
    for tr in tracks:
        m = tr.median()
        for big in merged:
            bm = big.median()
            if abs(bm[0] - m[0]) < max_dist and abs(bm[1] - m[1]) < max_dist * 1.5:
                big.points = sorted(big.points + tr.points)
                big.motion.update(tr.motion)
                break
        else:
            merged.append(tr)
    return merged


# ---------------------------------------------------------------- câmera virtual
JUMP_CONFIRM = 3          # um salto grande do alvo precisa se repetir em 3 amostras (ruído do detector)
CUT_DIFF_MIN = 28.0       # diferença média (0–255) entre quadros que indica troca de câmera
CUT_DIFF_RATIO = 4.0      # …e bem acima da diferença típica do vídeo


def smooth_path(times: list[float], targets: list[float | None], crop_w: float, fps: float,
                initial: float | None = None, cuts: list[float] | None = None) -> list[tuple[float, float]]:
    """Câmera com zona morta e limite de velocidade. Coordenadas normalizadas (centro do recorte).

    Na troca de câmera (`cuts`) a câmera vai direto para o rosto, sem panorâmica; fora dela, um salto grande do
    alvo só é seguido depois de confirmado em JUMP_CONFIRM amostras (ideia do OpenShorts, licença MIT).
    """
    if not times:
        return []
    known = [x for x in targets if x is not None]
    cam = initial if initial is not None else (known[0] if known else 0.5)
    dead = crop_w * 0.18
    max_speed = crop_w * 0.9  # por segundo
    dt = 1.0 / fps
    vel = 0.0
    out = []
    goal = cam
    cuts = sorted(cuts or [])
    ci = 0
    pending_cut = False
    jump_count = 0
    for t, x in zip(times, targets):
        while ci < len(cuts) and cuts[ci] <= t + 1e-6:
            pending_cut = True
            ci += 1
        if pending_cut and x is not None:
            cam = goal = x                      # troca de câmera: reposiciona na hora
            vel = 0.0
            pending_cut = False
            jump_count = 0
            out.append((t, cam))
            continue
        if x is not None and abs(x - cam) > crop_w * 0.5:
            jump_count += 1
            if jump_count < JUMP_CONFIRM:
                x = None                         # salto grande ainda não confirmado
        else:
            jump_count = 0
        if x is not None and abs(x - cam) > dead:
            goal = x
        diff = goal - cam
        desired = max(-max_speed, min(max_speed, diff * 2.5))
        vel = vel + (desired - vel) * 0.5
        cam += vel * dt
        if abs(goal - cam) < crop_w * 0.02:
            vel *= 0.5
        out.append((t, cam))
    return out


def clamp_center(cx: float, crop_w: float) -> float:
    half = crop_w / 2
    return min(max(cx, half), 1 - half) if crop_w < 1 else 0.5


def rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Simplificação Ramer–Douglas–Peucker para reduzir o número de keyframes."""
    if len(points) < 3:
        return points
    (t0, x0), (t1, x1) = points[0], points[-1]
    best_i, best_d = 0, 0.0
    for i in range(1, len(points) - 1):
        t, x = points[i]
        xi = x0 + (x1 - x0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
        d = abs(x - xi)
        if d > best_d:
            best_i, best_d = i, d
    if best_d <= eps:
        return [points[0], points[-1]]
    return rdp(points[: best_i + 1], eps)[:-1] + rdp(points[best_i:], eps)


# ---------------------------------------------------------------- análise principal
def analyze(src: Path, start: float, end: float, src_w: int, src_h: int, layout: str = "auto",
            manual_x: float | None = None, ctx: JobContext | None = None) -> dict:
    duration = end - start
    out_aspect = config.get("render.width") / config.get("render.height")
    crop_w = min(1.0, (src_h * out_aspect) / src_w)
    plan = {"layout": layout, "crop_w": crop_w, "keyframes": [], "faces": 0, "detector": None,
            "tracks": [], "note": ""}

    if crop_w >= 0.99:
        plan.update(layout="fit" if layout not in {"center", "manual"} else layout,
                    note="Vídeo já é vertical ou mais estreito que 9:16")
        plan["keyframes"] = [(0.0, 0.5)]
        if plan["layout"] != "fit":
            plan["layout"] = "center"
        return plan
    if layout == "manual":
        cx = clamp_center(0.5 if manual_x is None else float(manual_x), crop_w)
        plan["keyframes"] = [(0.0, cx)]
        return plan
    if layout in {"center", "fit"} or not config.get("render.face_tracking"):
        plan["layout"] = layout if layout in {"center", "fit"} else "center"
        plan["keyframes"] = [(0.0, 0.5)]
        if not config.get("render.face_tracking") and layout not in {"center", "fit"}:
            plan["note"] = "Rastreamento de rostos desativado nas configurações"
        return plan

    det = get_detector()
    if not det.available:
        plan.update(layout="center", keyframes=[(0.0, 0.5)], note="Nenhum detector de rosto disponível")
        return plan
    plan["detector"] = det.kind

    samples: list[tuple[float, list]] = []
    prev_gray = None
    diffs: list[tuple[float, float]] = []
    for t, frame in sample_frames(src, start, duration, src_w, src_h, ctx=ctx):
        faces = det.detect(frame)
        g = frame.mean(axis=2).astype(np.float32)
        if prev_gray is not None:
            diffs.append((t, float(np.abs(g[::8, ::8] - prev_gray[::8, ::8]).mean())))
        # guarda a energia de movimento da boca de cada rosto (usada no layout "speaker")
        samples.append((t, [(cx, cy, fw, fh, _region_motion(g, prev_gray, (cx, cy, fw, fh)))
                            for (cx, cy, fw, fh, _s) in faces]))
        prev_gray = g
        if ctx:
            ctx.progress(min(t / max(duration, 0.1), 1.0) * 0.9)
    if not samples:
        plan.update(layout="center", keyframes=[(0.0, 0.5)], note="Não foi possível ler quadros do vídeo")
        return plan

    cuts = scene_cuts(diffs)
    plan["cuts"] = [round(c, 2) for c in cuts]
    n = len(samples)
    tracks = _merge_tracks(_track(samples))
    tracks = [tr for tr in tracks if len(tr.points) >= max(3, 0.2 * n)]
    tracks.sort(key=lambda tr: -(len(tr.points) * tr.median()[2]))
    plan["faces"] = len(tracks)
    plan["tracks"] = [{"cx": round(tr.median()[0], 3), "cy": round(tr.median()[1], 3),
                       "presence": round(len(tr.points) / n, 2)} for tr in tracks[:4]]
    times = [t for t, _ in samples]

    if not tracks:
        plan.update(layout="center", keyframes=[(0.0, 0.5)], note="Nenhum rosto detectado; corte central")
        return plan

    two = [tr for tr in tracks[:2] if len(tr.points) >= 0.35 * n]
    far_apart = len(two) == 2 and abs(two[0].median()[0] - two[1].median()[0]) > crop_w * 0.8
    if layout == "auto":
        layout = "split" if far_apart else "follow"
    elif layout in {"split", "speaker"} and len(two) < 2:
        plan["note"] = "Apenas um rosto consistente encontrado; seguindo o rosto principal"
        layout = "follow"
    plan["layout"] = layout

    if layout == "split":
        # ordem da esquerda para a direita → painel de cima / de baixo
        panels = []
        for tr in sorted(two, key=lambda tr: tr.median()[0]):
            cx, cy, fw, fh = tr.median()
            panels.append({"cx": round(cx, 4), "cy": round(cy, 4), "fh": round(fh, 4)})
        plan["panels"] = panels
        plan["keyframes"] = [(0.0, 0.5)]
        return plan

    if layout == "speaker":
        targets = _speaker_targets(times, two, cuts=cuts)
        kf = [(t, clamp_center(x, crop_w)) for t, x in targets]
        plan["keyframes"] = _collapse_steps(kf)
        return plan

    # follow: rosto principal, com suavização
    main = tracks[0]
    by_t = {p[0]: p for p in main.points}
    faces_at = dict(samples)
    targets: list[float | None] = []
    cut_set = list(cuts)
    lost_after_cut = False
    for t in times:
        p = by_t.get(t)
        if any(abs(t - c) < 1e-6 or (c < t and c > t - 1.0 / SAMPLE_FPS) for c in cut_set):
            lost_after_cut = p is None
        if p:
            lost_after_cut = False
            targets.append(p[1])
        elif lost_after_cut and faces_at.get(t):
            # outra câmera e o rosto principal sumiu: segue o maior rosto da cena nova até ele voltar
            targets.append(max(faces_at[t], key=lambda f: f[2] * f[3])[0])
        else:
            targets.append(None)
    path = smooth_path(times, targets, crop_w, SAMPLE_FPS, initial=main.points[0][1], cuts=cuts)
    path = [(t, clamp_center(x, crop_w)) for t, x in path]
    plan["keyframes"] = rdp(path, eps=0.004)
    return plan


def _region_motion(g1: np.ndarray, g0: np.ndarray | None, face: tuple) -> float:
    """Energia de movimento na metade inferior do rosto entre quadros consecutivos."""
    if g0 is None:
        return 0.0
    cx, cy, fw, fh = face
    h, w = g1.shape
    x0, x1 = max(int((cx - fw * 0.35) * w), 0), min(int((cx + fw * 0.35) * w), w)
    y0, y1 = max(int((cy + fh * 0.05) * h), 0), min(int((cy + fh * 0.5) * h), h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 0.0
    r1, r0 = g1[y0:y1, x0:x1], g0[y0:y1, x0:x1]
    # remove a variação global de brilho subtraindo a média de cada região
    return float(np.abs((r1 - r1.mean()) - (r0 - r0.mean())).mean())


def scene_cuts(diffs: list[tuple[float, float]]) -> list[float]:
    """Trocas de câmera: diferença entre quadros muito acima da típica do vídeo."""
    if len(diffs) < 3:
        return []
    typical = float(np.median([d for _, d in diffs]))
    return [t for t, d in diffs if d >= CUT_DIFF_MIN and d >= CUT_DIFF_RATIO * max(typical, 1.0)]


def _normalized_motion(tr: Track) -> dict:
    """Movimento da boca na escala da própria pessoa (percentis 20–80).

    Sem isso, quem está mais perto da câmera ou mais iluminado "fala" sempre mais (ideia do OpenShorts, MIT).
    """
    vals = np.array(list(tr.motion.values()), dtype=float)
    if len(vals) < 4:
        return dict(tr.motion)
    lo, hi = np.percentile(vals, 20), np.percentile(vals, 80)
    span = max(hi - lo, 1e-6)
    return {t: (v - lo) / span for t, v in tr.motion.items()}


def _speaker_targets(times: list[float], tracks: list[Track], window: float = 1.5,
                     min_shot: float = 2.0, margin: float = 0.15, confirm: int = 3,
                     cuts: list[float] | None = None) -> list[tuple[float, float]]:
    """Enquadra quem está falando: troca só com vantagem clara (margem), confirmada em `confirm` amostras
    seguidas e depois de pelo menos `min_shot` segundos no mesmo plano (exceto numa troca de câmera)."""
    centers = [tr.median()[0] for tr in tracks]
    motion = [_normalized_motion(tr) for tr in tracks]
    cuts = sorted(cuts or [])
    current = 0
    last_switch = -min_shot
    streak = 0
    out = []
    for t in times:
        energies = []
        for m in motion:
            vals = [v for tt, v in m.items() if t - window <= tt <= t]
            energies.append(sum(vals) / len(vals) if vals else 0.0)
        other = 1 - current
        after_cut = any(t - 1.0 <= c <= t for c in cuts)
        if energies[other] - energies[current] >= margin and energies[other] > 0.35:
            streak += 1
        else:
            streak = 0
        if streak >= confirm and (t - last_switch >= min_shot or after_cut):
            current = other
            last_switch = t
            streak = 0
        out.append((t, centers[current]))
    return out


def _collapse_steps(kf: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Converte uma sequência em degraus (cortes secos entre participantes)."""
    if not kf:
        return kf
    out = [kf[0]]
    for t, x in kf[1:]:
        if abs(x - out[-1][1]) > 1e-4:
            out.append((max(t - 0.001, out[-1][0] + 0.0005), out[-1][1]))
            out.append((t, x))
    if out[-1][0] < kf[-1][0]:
        out.append((kf[-1][0], out[-1][1]))
    return out
