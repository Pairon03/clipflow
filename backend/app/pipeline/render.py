"""Renderização final de cada Short com FFmpeg (H.264 + AAC, 1080x1920)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import enhance, ffmpeg, framing, overlay, subtitles
from .context import JobContext
from .errors import PipelineError

FADE_IN = 0.15
TITLE_START_S = 4.0  # duração do título no modo "só no início"
FADE_OUT = 0.25
MAX_KEYFRAMES = 80


# ---------------------------------------------------------------- tempo
@dataclass
class TimeMap:
    """Mapeia tempo relativo ao início do corte → tempo do vídeo final (após remover pausas)."""

    intervals: list[tuple[float, float]]
    speed: float = 1.0  # >1 acelera (o vídeo final fica mais curto)

    @property
    def duration(self) -> float:
        return sum(b - a for a, b in self.intervals) / self.speed

    def map(self, t: float) -> float:
        acc = 0.0
        for a, b in self.intervals:
            if t < a:
                return acc / self.speed  # dentro de uma pausa removida: encosta no próximo trecho
            if t <= b:
                return (acc + (t - a)) / self.speed
            acc += b - a
        return acc / self.speed


# Ritmo: até quanto silêncio entre palavras é mantido e quanto de "respiro" fica em cada lado do corte
PACES = {
    "natural": {"max_pause": 0.7, "keep_pad": 0.15},
    "tiktok": {"max_pause": 0.28, "keep_pad": 0.07},  # corta respirações e hesitações
}
MIN_SPEED, MAX_SPEED = 1.0, 1.25


def keep_intervals(words: list[dict], clip_start: float, clip_end: float, trim: bool,
                   max_pause: float = 0.7, keep_pad: float = 0.15) -> list[tuple[float, float]]:
    """Intervalos (relativos ao início do corte) a manter. Pausas maiores que `max_pause` são removidas,
    sobrando só `keep_pad` de cada lado (no ritmo TikTok, as respirações entre frases somem)."""
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
            if cut_b - cut_a > 0.08:
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


def snap_intervals(intervals: list[tuple[float, float]], fps: float) -> list[tuple[float, float]]:
    """Alinha os cortes à grade de quadros do vídeo, para áudio e vídeo cortarem exatamente juntos."""
    out = []
    for a, b in intervals:
        fa, fb = round(a * fps), round(b * fps)
        if fb > fa:
            out.append((round(fa / fps, 6), round(fb / fps, 6)))
    return out or [(0.0, round(max(intervals[-1][1], 1 / fps), 6))]


def _select_expr(intervals: list[tuple[float, float]], fps: float) -> str:
    half = 0.5 / fps
    return "+".join(f"between(t,{a:.4f},{b - half:.4f})" for a, b in intervals)


def build_filtergraph(intervals: list[tuple[float, float]], plan: dict, src_w: int, src_h: int, fps: float,
                      ass_path: Path | None, out_duration: float, speed: float = 1.0,
                      hook_len: float | None = None, overlay_input: int | None = None,
                      overlay_until: float | None = None) -> str:
    """Monta o filtro do FFmpeg.

    Os trechos mantidos são escolhidos numa única passada (select/aselect), sem duplicar o vídeo
    para cada corte: assim a memória não cresce com o número de cortes (ritmo TikTok).
    O áudio é fatiado em blocos do tamanho de um quadro, então os dois cortam no mesmo ponto.
    `hook_len`: gancho de abertura, lido da 2ª entrada ([1:v]/[1:a]) e colocado antes de tudo.
    """
    out_w, out_h = config.get("render.width"), config.get("render.height")
    parts: list[str] = []
    nsamples = max(1, round(48000 / fps))
    expr = _select_expr(intervals, fps)
    main_v, main_a = ("vm", "am") if hook_len else ("vc", "ac")
    parts.append(f"[0:v]setpts=PTS-STARTPTS,fps={fps:g},select='{expr}',setpts=N/({fps:g}*TB)[{main_v}]")
    parts.append(f"[0:a]asetpts=PTS-STARTPTS,aresample=48000,asetnsamples=n={nsamples}:p=0,"
                 f"aselect='{expr}',asetpts=N/SR/TB[{main_a}]")
    if hook_len:
        parts.append(f"[1:v]setpts=PTS-STARTPTS,fps={fps:g},trim=end={hook_len:.4f},setpts=PTS-STARTPTS[vh]")
        parts.append(f"[1:a]asetpts=PTS-STARTPTS,aresample=48000,atrim=end={hook_len:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=out:st={max(hook_len - 0.03, 0):.3f}:d=0.03[ah]")
        parts.append("[vh][ah][vm][am]concat=n=2:v=1:a=1[vc][ac]")
    speed_v = f"setpts=PTS/{speed:g}," if speed != 1.0 else ""
    parts.append(f"[vc]{speed_v}fps={fps:g}[vf]")
    parts.append(layout_filter(plan, src_w, src_h, out_w, out_h, "vf", "vlay"))
    if overlay_input is not None:
        # título (PNG transparente do tamanho do vídeo) com entrada suave; some no fim se for "só no início"
        fade = "fade=t=in:st=0:d=0.3:alpha=1"
        if overlay_until:
            fade += f",fade=t=out:st={max(overlay_until - 0.3, 0):.3f}:d=0.3:alpha=1"
        parts.append(f"[{overlay_input}:v]format=rgba,{fade}[ttl]")
        parts.append("[vlay][ttl]overlay=0:0:format=auto:shortest=1[vl]")
    else:
        parts.append("[vlay]null[vl]")
    post = []
    if ass_path is not None:
        fonts = subtitles.ffmpeg_filter_path(config.FONTS_DIR)
        post.append(f"ass=filename='{subtitles.ffmpeg_filter_path(ass_path)}':fontsdir='{fonts}'")
    fo_start = max(out_duration - FADE_OUT, 0)
    post.append(f"fade=t=in:st=0:d={FADE_IN},fade=t=out:st={fo_start:.3f}:d={FADE_OUT}")
    post.append("format=yuv420p")
    parts.append(f"[vl]{','.join(post)}[vout]")
    audio = [f"atempo={speed:g}"] if speed != 1.0 else []  # acelera mantendo o tom de voz
    if config.get("render.loudnorm"):
        audio.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    audio.append(f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fo_start:.3f}:d={FADE_OUT}")
    audio.append("aresample=48000")
    parts.append(f"[ac]{','.join(audio)}[aout]")
    return ";".join(parts)


# ---------------------------------------------------------------- render
def storage_remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _interp(keyframes: list[tuple[float, float]], t: float) -> float:
    if not keyframes:
        return 0.5
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    for (t0, x0), (t1, x1) in zip(keyframes, keyframes[1:]):
        if t0 <= t <= t1:
            return x0 + (x1 - x0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    return keyframes[-1][1]


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
    pace = PACES.get(options.get("pace", ""), None)
    max_pause = pace["max_pause"] if pace else float(options.get("max_pause", 0.7))
    keep_pad = pace["keep_pad"] if pace else 0.15
    speed = min(max(float(options.get("speed", 1.0) or 1.0), MIN_SPEED), MAX_SPEED)
    intervals = snap_intervals(keep_intervals(words, start, end, trim=bool(options.get("trim_silence", True)),
                                              max_pause=max_pause, keep_pad=keep_pad), fps)
    tmap = TimeMap(intervals, speed)
    # gancho de abertura: a fala mais chamativa toca primeiro e o vídeo segue do começo
    hook = enhance.pick_cold_open(words, start, end) if options.get("cold_open", False) else None
    if hook:
        hook = snap_intervals([hook], fps)[0]
    hook_out = round((hook[1] - hook[0]) / speed, 3) if hook else 0.0
    out_duration = round(hook_out + tmap.duration, 3)
    source_kf = plan.get("keyframes", [])
    plan["keyframes"] = [(round(hook_out + tmap.map(t), 3), x) for t, x in source_kf]
    if hook:
        xh = _interp(source_kf, (hook[0] + hook[1]) / 2)
        plan["keyframes"] = [(0.0, xh), (max(hook_out - 0.001, 0.0005), xh)] + plan["keyframes"]
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
    if hook:
        for w in words:
            rs, re_ = w["start"] - start, w["end"] - start
            if rs >= hook[0] - 0.01 and re_ <= hook[1] + 0.05:
                s0 = (rs - hook[0]) / speed
                e0 = min(max((re_ - hook[0]) / speed, s0 + 0.04), hook_out)
                out_words.append({"text": w["text"], "start": round(s0, 3), "end": round(e0, 3)})
    for w in words:
        s = hook_out + tmap.map(w["start"] - start)
        e = hook_out + tmap.map(w["end"] - start)
        if e - s < 0.04:
            e = s + 0.04
        out_words.append({"text": w["text"], "start": round(s, 3), "end": round(min(e, out_duration), 3)})
    clip_id = clip["id"]
    split = plan["layout"] == "split"
    title_style = options.get("title_style_resolved") or "nenhum"
    card_png = None
    if title_style != "nenhum" and options.get("title_card"):
        # no layout dividido o título vai para a divisão entre as duas pessoas
        card_png = overlay.render_card(title_style, options["title_card"], work_dir / f"{clip_id}{variant}.title.png",
                                       out_w, out_h, position="middle" if split else "top")
    overlay_until = None
    if card_png and options.get("title_duration") == "inicio":
        overlay_until = min(TITLE_START_S, out_duration)
    ass_path = None
    if options.get("captions", True) and out_words:
        style = subtitles.resolve_style(options.get("caption_style", "classic"), options.get("caption_colors"))
        below = None
        if card_png and split:  # legenda (no meio) desce para baixo do título enquanto ele aparece
            from PIL import Image

            with Image.open(card_png) as im:
                bbox = im.getchannel("A").getbbox()
            if bbox:
                below = (overlay_until, bbox[3])
        ass_path = subtitles.build_ass(out_words, style, out_w, out_h, sub_dir / f"{clip_id}.ass",
                                       centered=split, below=below)
    srt_path = subtitles.build_srt(out_words, sub_dir / f"{clip_id}.srt") if out_words else None

    # 4) FFmpeg
    ctx.span(a + (b - a) * 0.35, a + (b - a) * 0.92, ctx.stage)
    overlay_idx = (2 if hook else 1) if card_png else None
    graph = build_filtergraph(intervals, plan, src_w, src_h, fps, ass_path, out_duration, speed,
                              hook_len=(hook[1] - hook[0]) if hook else None,
                              overlay_input=overlay_idx, overlay_until=overlay_until)
    (work_dir / f"{clip_id}.filtergraph.txt").write_text(graph, encoding="utf-8")
    # `variant` gera um arquivo à parte (ex.: "_clean", sem legenda, para edição no Concat)
    tmp_out = work_dir / f"{clip_id}{variant}.partial.mp4"
    final = out_dir / f"{clip_id}{variant}.mp4"
    args = [
        "-ss", f"{start:.3f}", "-t", f"{end - start + 0.1:.3f}", "-i", str(src),
        *(["-ss", f"{start + hook[0]:.3f}", "-t", f"{hook[1] - hook[0] + 0.1:.3f}", "-i", str(src)] if hook else []),
        *(["-loop", "1", "-framerate", str(fps), "-t", f"{out_duration + 0.5:.3f}", "-i", str(card_png)]
          if card_png else []),
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", config.get("render.video_preset"), "-crf", str(config.get("render.crf")),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", config.get("render.audio_bitrate"), "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{out_duration:.3f}", str(tmp_out),
    ]
    ffmpeg.run(args, ctx=ctx, duration=out_duration, on_progress=ctx.progress)
    if card_png:
        storage_remove(card_png)

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
                        "intervals": len(intervals), "removed_pause_s": round((end - start) - tmap.duration * speed, 2),
                        "speed": speed, "pace": options.get("pace", "natural"),
                        "cold_open": [hook[0], hook[1]] if hook else None,
                        "title_style": title_style if card_png else None,
                        "fps": fps, "tracks": plan.get("tracks", [])},
    }
