"""Renderização final de cada Short com FFmpeg (H.264 + AAC, 1080x1920)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import ffmpeg, framing, subtitles
from .context import JobContext
from .errors import PipelineError

FADE_IN = 0.15
FADE_OUT = 0.25
MAX_KEYFRAMES = 80


# ---------------------------------------------------------------- tempo
@dataclass
class TimeMap:
    """Mapeia tempo relativo ao início do corte → tempo do vídeo final (após remover pausas)."""

    intervals: list[tuple[float, float]]

    @property
    def duration(self) -> float:
        return sum(b - a for a, b in self.intervals)

    def map(self, t: float) -> float:
        acc = 0.0
        for a, b in self.intervals:
            if t < a:
                return acc  # dentro de uma pausa removida: encosta no próximo trecho
            if t <= b:
                return acc + (t - a)
            acc += b - a
        return acc


def keep_intervals(words: list[dict], clip_start: float, clip_end: float, trim: bool,
                   max_pause: float = 0.7, keep_pad: float = 0.15) -> list[tuple[float, float]]:
    """Intervalos (relativos ao início do corte) a manter. Pausas longas viram pausas curtas."""
    dur = clip_end - clip_start
    if not trim or len(words) < 2:
        return [(0.0, dur)]
    out: list[tuple[float, float]] = []
    cur_a = 0.0
    for w, nxt in zip(words, words[1:]):
        gap = nxt["start"] - w["end"]
        if gap > max_pause:
            cut_a = w["end"] - clip_start + keep_pad
            cut_b = nxt["start"] - clip_start - keep_pad
            if cut_b - cut_a > 0.2:
                out.append((cur_a, cut_a))
                cur_a = cut_b
    out.append((cur_a, dur))
    return [(round(max(a, 0), 3), round(min(b, dur), 3)) for a, b in out if b - a > 0.05]


def words_for_clip(transcript_words: list[dict], start: float, end: float) -> list[dict]:
    return [dict(w) for w in transcript_words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


# ---------------------------------------------------------------- filtros
def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def crop_x_expr(keyframes: list[tuple[float, float]], src_w: int, crop_px: int) -> str:
    """Expressão do FFmpeg (variável t) com interpolação linear entre keyframes, em pixels."""
    max_x = max(src_w - crop_px, 0)

    def px(cx: float) -> float:
        return round(min(max(cx * src_w - crop_px / 2, 0), max_x), 1)

    if not keyframes:
        return str(px(0.5))
    kf = [(round(t, 3), px(x)) for t, x in keyframes]
    if len(kf) == 1:
        return str(kf[0][1])
    expr = str(kf[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(kf, kf[1:]))):
        if t1 <= t0:
            continue
        seg = f"{x0}+({x1 - x0})*(t-{t0})/{round(t1 - t0, 4)}"
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return f"if(lt(t,{kf[0][0]}),{kf[0][1]},{expr})"


def layout_filter(plan: dict, src_w: int, src_h: int, out_w: int, out_h: int, inp: str, outp: str) -> str:
    layout = plan["layout"]
    if layout == "fit":
        return (f"[{inp}]split[fbg][ffg];"
                f"[fbg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                f"boxblur=24:2,eq=brightness=-0.08[bgb];"
                f"[ffg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[{outp}]")
    if layout == "split" and len(plan.get("panels", [])) == 2:
        panel_h = out_h // 2
        aspect = out_w / panel_h
        parts = [f"[{inp}]split[sp0][sp1]"]
        for i, p in enumerate(plan["panels"]):
            ch = min(max(p["fh"] * src_h * 4.0, src_h * 0.55), src_h)
            cw = ch * aspect
            if cw > src_w:
                cw, ch = src_w, src_w / aspect
            cw, ch = _even(cw), _even(ch)
            x = min(max(p["cx"] * src_w - cw / 2, 0), src_w - cw)
            y = min(max(p["cy"] * src_h - ch * 0.42, 0), src_h - ch)
            parts.append(f"[sp{i}]crop={cw}:{ch}:{int(x)}:{int(y)},scale={out_w}:{panel_h}:flags=lanczos,setsar=1[pn{i}]")
        parts.append(f"[pn0][pn1]vstack=inputs=2[{outp}]")
        return ";".join(parts)
    # follow / speaker / center / manual: recorte vertical com x animado
    crop_px = min(_even(src_h * out_w / out_h), src_w - (src_w % 2))
    kf = plan.get("keyframes") or [(0.0, 0.5)]
    if len(kf) > MAX_KEYFRAMES:
        eps = 0.004
        while len(kf) > MAX_KEYFRAMES:
            eps *= 1.6
            kf = framing.rdp(kf, eps)
    expr = crop_x_expr(kf, src_w, crop_px)
    return (f"[{inp}]crop=w={crop_px}:h={src_h - (src_h % 2)}:x='{expr}':y=0,"
            f"scale={out_w}:{out_h}:flags=lanczos,setsar=1[{outp}]")


def build_filtergraph(intervals: list[tuple[float, float]], plan: dict, src_w: int, src_h: int, fps: float,
                      ass_path: Path | None, out_duration: float) -> str:
    out_w, out_h = config.get("render.width"), config.get("render.height")
    parts: list[str] = []
    if len(intervals) == 1:
        a, b = intervals[0]
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[vc]")
        parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[ac]")
    else:
        labels = []
        for i, (a, b) in enumerate(intervals):
            parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
            parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        parts.append(f"{''.join(labels)}concat=n={len(intervals)}:v=1:a=1[vc][ac]")
    parts.append(f"[vc]fps={fps:g}[vf]")
    parts.append(layout_filter(plan, src_w, src_h, out_w, out_h, "vf", "vl"))
    post = []
    if ass_path is not None:
        fonts = subtitles.ffmpeg_filter_path(config.FONTS_DIR)
        post.append(f"ass=filename='{subtitles.ffmpeg_filter_path(ass_path)}':fontsdir='{fonts}'")
    fo_start = max(out_duration - FADE_OUT, 0)
    post.append(f"fade=t=in:st=0:d={FADE_IN},fade=t=out:st={fo_start:.3f}:d={FADE_OUT}")
    post.append("format=yuv420p")
    parts.append(f"[vl]{','.join(post)}[vout]")
    audio = []
    if config.get("render.loudnorm"):
        audio.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    audio.append(f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fo_start:.3f}:d={FADE_OUT}")
    audio.append("aresample=48000")
    parts.append(f"[ac]{','.join(audio)}[aout]")
    return ";".join(parts)


# ---------------------------------------------------------------- render
def render_clip(src: Path, src_info: dict, clip: dict, words: list[dict], options: dict,
                out_dir: Path, sub_dir: Path, work_dir: Path, ctx: JobContext, variant: str = "") -> dict:
    """Renderiza um corte. Retorna informações do resultado. Lança PipelineError em falha."""
    start, end = float(clip["start"]), float(clip["end"])
    if end - start < 1.0:
        raise PipelineError("Corte muito curto")
    src_w, src_h = int(src_info["width"]), int(src_info["height"])
    out_w, out_h = config.get("render.width"), config.get("render.height")
    fps = min(round(src_info.get("fps") or 30), config.get("render.fps_max")) or 30

    # 1) enquadramento (0–35%)
    ctx_frac = ctx._span
    a, b = ctx_frac
    ctx.span(a, a + (b - a) * 0.35, ctx.stage)
    layout = clip.get("layout") or options.get("layout") or "auto"
    plan = framing.analyze(src, start, end, src_w, src_h, layout=layout,
                           manual_x=clip.get("manual_x"), ctx=ctx)
    ctx.check()

    # 2) linha do tempo final (remoção de pausas longas)
    intervals = keep_intervals(words, start, end, trim=bool(options.get("trim_silence", True)),
                               max_pause=float(options.get("max_pause", 0.7)))
    tmap = TimeMap(intervals)
    out_duration = round(tmap.duration, 3)
    plan["keyframes"] = [(round(tmap.map(t), 3), x) for t, x in plan.get("keyframes", [])]
    # remove keyframes duplicados que caíram no mesmo instante após o mapeamento
    dedup: list[tuple[float, float]] = []
    for t, x in plan["keyframes"]:
        if dedup and t <= dedup[-1][0]:
            if t == dedup[-1][0] and abs(x - dedup[-1][1]) > 1e-4:
                dedup.append((t + 0.0005, x))
            continue
        dedup.append((t, x))
    plan["keyframes"] = dedup

    # 3) legendas no tempo final
    out_words = []
    for w in words:
        s = tmap.map(w["start"] - start)
        e = tmap.map(w["end"] - start)
        if e - s < 0.04:
            e = s + 0.04
        out_words.append({"text": w["text"], "start": round(s, 3), "end": round(min(e, out_duration), 3)})
    clip_id = clip["id"]
    ass_path = None
    if options.get("captions", True) and out_words:
        style = subtitles.resolve_style(options.get("caption_style", "classic"), options.get("caption_colors"))
        ass_path = subtitles.build_ass(out_words, style, out_w, out_h, sub_dir / f"{clip_id}.ass",
                                       centered=plan["layout"] == "split")
    srt_path = subtitles.build_srt(out_words, sub_dir / f"{clip_id}.srt") if out_words else None

    # 4) FFmpeg
    ctx.span(a + (b - a) * 0.35, a + (b - a) * 0.92, ctx.stage)
    graph = build_filtergraph(intervals, plan, src_w, src_h, fps, ass_path, out_duration)
    (work_dir / f"{clip_id}.filtergraph.txt").write_text(graph, encoding="utf-8")
    # `variant` gera um arquivo à parte (ex.: "_clean", sem legenda, para edição no Concat)
    tmp_out = work_dir / f"{clip_id}{variant}.partial.mp4"
    final = out_dir / f"{clip_id}{variant}.mp4"
    args = [
        "-ss", f"{start:.3f}", "-t", f"{end - start + 0.1:.3f}", "-i", str(src),
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", config.get("render.video_preset"), "-crf", str(config.get("render.crf")),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", config.get("render.audio_bitrate"), "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{out_duration:.3f}", str(tmp_out),
    ]
    ffmpeg.run(args, ctx=ctx, duration=out_duration, on_progress=ctx.progress)

    # 5) verificação de integridade + miniatura
    ctx.span(a + (b - a) * 0.92, b, ctx.stage)
    info = ffmpeg.verify_output(tmp_out, out_duration, out_w, out_h,
                                decode=bool(config.get("render.verify_decode")), ctx=ctx)
    tmp_out.replace(final)
    thumb = out_dir / f"{clip_id}{variant}.jpg"
    try:
        ffmpeg.thumbnail(final, thumb, at=min(1.5, out_duration / 2))
    except PipelineError:
        thumb = None
    ctx.progress(1.0)
    return {
        "output_path": str(final), "thumb_path": str(thumb) if thumb else None,
        "srt_path": str(srt_path) if srt_path else None, "duration": info["duration"],
        "size_bytes": final.stat().st_size,
        "words_out": out_words,
        "render_info": {"layout": plan["layout"], "detector": plan.get("detector"), "faces": plan.get("faces"),
                        "note": plan.get("note", ""), "keyframes": len(plan.get("keyframes", [])),
                        "intervals": len(intervals), "removed_pause_s": round((end - start) - out_duration, 2),
                        "fps": fps, "tracks": plan.get("tracks", [])},
    }
