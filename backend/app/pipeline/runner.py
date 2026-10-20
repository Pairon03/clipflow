"""Orquestração das etapas: análise (obter → transcrever → selecionar) e renderização."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from .. import config, db, storage
from . import audio as audio_mod
from . import censor, ffmpeg, hooks, llm, metadata, render, selection, transcribe, youtube
from .context import JobContext
from .errors import Cancelled, FatalPipelineError, PipelineError

PROJECT_FINAL = {"completed", "failed", "cancelled", "awaiting_review"}


def _project(pid: str) -> dict:
    p = db.fetch_one("SELECT * FROM projects WHERE id = ?", (pid,))
    if not p:
        raise FatalPipelineError("Projeto não encontrado")
    return p


def transcript_path(pid: str) -> Path:
    return storage.area_dir("transcripts", pid) / "transcript.json"


def profile_path(pid: str) -> Path:
    return storage.area_dir("transcripts", pid) / "audio_energy.npz"


def load_profile(pid: str) -> dict | None:
    p = profile_path(pid)
    if not p.exists():
        return None
    data = np.load(p)
    return {"window": float(data["window"]), "rms_db": data["rms_db"], "clip": data["clip"]}


def find_source_subtitle(pid: str) -> Path | None:
    d = storage.area_dir("downloads", pid)
    for ext in (".srt", ".vtt"):
        f = d / f"subtitles{ext}"
        if f.exists():
            return f
    return None


# ================================================================ ANÁLISE
def run_analysis(pid: str, ctx: JobContext) -> str:
    """Retorna o próximo passo: 'render' ou 'review'."""
    # sem FFmpeg nada funciona (nem o download do YouTube): avisa antes de começar
    ffmpeg.ffmpeg_bin()
    ffmpeg.ffprobe_bin()
    p = _project(pid)
    opts = p["options"] or {}
    dl_dir = storage.area_dir("downloads", pid)
    tr_dir = storage.area_dir("transcripts", pid)

    # 1) obter vídeo
    src = Path(p["source_path"]) if p["source_path"] else None
    if p["source_type"] == "youtube" and (not src or not src.exists()):
        ctx.span(0.0, 0.15, "Baixando vídeo autorizado")
        db.update("projects", pid, status="downloading")
        ctx.log.info("Download via yt-dlp: %s", p["source_url"])
        vid = p["source_key"].split(":", 1)[1]
        src = youtube.download(vid, dl_dir, ctx)
    if not src or not src.exists():
        raise FatalPipelineError("Arquivo de origem não encontrado")
    storage.ensure_inside_root(src)
    ctx.check()

    info = ffmpeg.probe(src)
    if not info.has_audio:
        raise FatalPipelineError("O vídeo não tem trilha de áudio — não é possível transcrever")
    max_min = config.get("limits.max_source_minutes")
    if info.duration > max_min * 60:
        raise FatalPipelineError(f"Vídeo com {info.duration / 60:.0f} min excede o limite de {max_min} min")
    db.update("projects", pid, source_path=str(src), source_duration=info.duration, source_width=info.width,
              source_height=info.height, source_size=info.size)
    ctx.log.info("Origem: %s (%.1fs, %dx%d, %.1f fps)", src.name, info.duration, info.width, info.height, info.fps)

    # 2) transcrição (reaproveita se já existir)
    tpath = transcript_path(pid)
    if tpath.exists():
        ctx.log.info("Reaproveitando transcrição existente")
        transcript = transcribe.load(tpath)
    else:
        db.update("projects", pid, status="transcribing")
        wav = tr_dir / "audio.wav"
        ctx.span(0.15, 0.22, "Extraindo áudio")
        ffmpeg.extract_audio(src, wav, ctx=ctx, duration=info.duration, on_progress=ctx.progress)
        prof = audio_mod.energy_profile(wav)
        np.savez_compressed(profile_path(pid), window=prof["window"], rms_db=prof["rms_db"], clip=prof["clip"])
        ctx.check()
        sub = find_source_subtitle(pid)
        if sub:
            ctx.span(0.22, 0.75, "Importando legenda enviada")
            transcript = transcribe.import_subtitles(sub, info.duration)
        else:
            ctx.span(0.22, 0.75, "Transcrevendo (Whisper)")
            transcript = transcribe.transcribe_whisper(wav, info.duration, ctx)
        storage.remove_quietly(wav)  # áudio temporário removido após o uso
        if not transcript["segments"]:
            raise FatalPipelineError("Nenhuma fala foi detectada no vídeo")
        transcribe.save(transcript, tpath)
        transcribe.to_srt(transcript["segments"], tr_dir / "transcript.srt")
        n_words = sum(len(s["words"]) for s in transcript["segments"])
        ctx.log.info("Transcrição pronta: %d segmentos, %d palavras (%s)",
                     len(transcript["segments"]), n_words, transcript["engine"])
    ctx.check()

    # 3) seleção de cortes
    ctx.span(0.75, 0.97, "Selecionando melhores momentos")
    db.update("projects", pid, status="analyzing")
    select_clips(pid, transcript, opts, ctx)
    ctx.progress(1.0)
    return "review" if opts.get("review") else "render"


def select_clips(pid: str, transcript: dict, opts: dict, ctx: JobContext | None = None) -> list[dict]:
    count = int(opts.get("count", 5))
    min_s, max_s = float(opts.get("min_duration", 30)), float(opts.get("max_duration", 60))
    profile = load_profile(pid)
    chosen, alternatives = selection.find_clips(transcript, count, min_s, max_s, profile,
                                                style=opts.get("style", "podcast_premium"))
    if not chosen:
        raise FatalPipelineError("Não foram encontrados trechos com a duração pedida. "
                                 "Tente uma faixa de duração diferente.")
    if ctx:
        ctx.progress(0.5)
    engine = "heuristica"
    if llm.enabled():
        pool = sorted(chosen + alternatives, key=lambda c: -c.score)[:15]
        result = llm.rerank([{"id": i, "text": c.text} for i, c in enumerate(pool)])
        if result:
            engine = "ollama+heuristica"
            for i, c in enumerate(pool):
                if i in result:
                    c.score = round(0.7 * c.score + 0.3 * result[i]["nota"] * 10, 1)
                    c.scores["ia_local"] = result[i]["nota"] / 10
                    if result[i]["motivo"]:
                        c.reasons.append("IA local: " + result[i]["motivo"])
            chosen, alternatives = selection.select(pool + [a for a in alternatives if a not in pool], count)
        elif ctx:
            ctx.log.warning("Ollama ativado mas indisponível; usando apenas o motor heurístico")
    now = db.now()
    with db.conn() as c:
        c.execute("DELETE FROM clips WHERE project_id = ? AND status IN ('candidate', 'selected', 'failed')", (pid,))
        # Shorts já renderizados continuam na biblioteca, mas saem da seleção atual
        c.execute("UPDATE clips SET selected = 0 WHERE project_id = ? AND status = 'done'", (pid,))
        rows = []
        for rank, cand in enumerate(chosen):
            rows.append((cand, 1, rank))
        for rank, cand in enumerate(alternatives):
            rows.append((cand, 0, rank + len(chosen)))
        for cand, sel, rank in rows:
            d = cand.as_dict()
            c.execute(
                "INSERT INTO clips (id, project_id, rank, start, end, text, category, score, scores_json, "
                "reasons_json, selected, status, created_at, layout) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (db.new_id(), pid, rank, d["start"], d["end"], d["text"], d["category"], d["score"],
                 json.dumps(d["scores"]), json.dumps(d["reasons"], ensure_ascii=False), sel,
                 "selected" if sel else "candidate", now, opts.get("layout", "auto")),
            )
    if ctx:
        ctx.log.info("%d cortes selecionados, %d alternativas (motor: %s)", len(chosen), len(alternatives), engine)
    if opts.get("cold_open", False) and ctx:  # só na fila: a reseleção pela API é síncrona (gancho sai no render)
        ctx.span(*ctx._span, "Escolhendo ganchos")
        all_words = transcribe.all_words(transcript)
        for clip in db.fetch_all("SELECT * FROM clips WHERE project_id = ? AND selected = 1 AND status = 'selected' "
                                 "ORDER BY start", (pid,)):
            ensure_hook(clip, render.words_for_clip(all_words, clip["start"], clip["end"]), opts, ctx)
    return [c.as_dict() for c in chosen]


def ensure_hook(clip: dict, words: list[dict], opts: dict, ctx: JobContext | None = None) -> dict | None:
    """Gancho do corte: reaproveita o salvo se o corte não mudou; senão avalia de novo e salva.

    A escolha manual (hook.choice) é mantida enquanto início/fim do corte forem os mesmos.
    """
    if not opts.get("cold_open", False):
        return None
    saved = clip.get("hook")
    if hooks.is_current(saved, clip["start"], clip["end"]):
        return saved
    result = hooks.analyze(words, clip["start"], clip["end"], use_llm=True,
                           timeout=float(config.get("ai.hook_timeout_s")))
    db.update("clips", clip["id"], hook_json=result)
    clip["hook"] = result
    if ctx:
        ch = result["chosen"]
        txt = result["candidates"][ch]["clean"] if ch is not None else None
        ctx.log.info("Gancho do corte %s (%s, %.1fs): %s", clip["id"], result["engine"], result["elapsed_s"],
                     f"“{txt}” nota {result['candidates'][ch]['total']}" if txt else f"sem gancho — {result['reason']}")
    return result


def _hook_options(clip: dict, words: list[dict], opts: dict, ctx: JobContext | None) -> dict:
    """Opções de render com o gancho já escolhido (o render não decide mais sozinho)."""
    if not opts.get("cold_open", False):
        return {}
    h = ensure_hook(clip, words, opts, ctx)
    interval = hooks.selected(h, clip["start"], clip["end"])
    meta = None
    if h:
        idx = h.get("choice") if isinstance(h.get("choice"), int) else h.get("chosen")
        if interval and idx is not None:
            c = h["candidates"][idx]
            meta = {"text": c["clean"], "total": c["total"], "scores": c["scores"], "engine": h["engine"],
                    "manual": isinstance(h.get("choice"), int), "payoff": c["payoff"]}
        else:
            meta = {"text": None, "engine": h["engine"], "manual": h.get("choice") == "none",
                    "reason": "escolha manual: sem gancho" if h.get("choice") == "none" else h.get("reason", "")}
    return {"hook_interval": interval, "hook_meta": meta}


# ================================================================ RENDER
def _render_one(src: Path, info: dict, clip: dict, words: list[dict], opts: dict, meta: dict,
                out_dir: Path, sub_dir: Path, work_dir: Path, ctx: JobContext) -> dict:
    """Renderiza com o motor escolhido. Se o Concat falhar ou não existir, usa o FFmpeg e registra o motivo."""
    if opts.get("engine") == "concat":
        from . import concat_bridge

        exe = concat_bridge.find_executable()
        if not exe:
            ctx.log.warning("Motor Concat escolhido, mas o Concat não foi encontrado; usando FFmpeg")
            note = "Concat não encontrado; renderizado com FFmpeg"
        else:
            span = ctx._span
            try:
                return _render_with_concat(exe, src, info, clip, words, opts, meta, out_dir, sub_dir, work_dir, ctx)
            except concat_bridge.McpError as exc:
                ctx.log.warning("Concat falhou em %s (%s); usando FFmpeg", clip["id"], exc)
                note = f"Concat falhou ({str(exc)[:120]}); renderizado com FFmpeg"
                ctx.span(span[0], span[1], ctx.stage)
        result = render.render_clip(src, info, clip, words, opts, out_dir, sub_dir, work_dir, ctx)
        ri = result["render_info"]
        ri["engine"] = "ffmpeg"
        ri["note"] = f"{ri['note']} · {note}" if ri.get("note") else note
        return result
    result = render.render_clip(src, info, clip, words, opts, out_dir, sub_dir, work_dir, ctx)
    result["render_info"]["engine"] = "ffmpeg"
    return result


def _clip_options(opts: dict, meta: dict, clip: dict, index: int | None) -> dict:
    """Opções de render de um corte: estilo do título já resolvido (inclusive o "variar") e o texto dele."""
    from . import overlay

    style = opts.get("title_style")
    if style is None:  # projetos antigos: "theme" ligado vira o cartão padrão
        style = "tweet" if opts.get("theme", True) else "nenhum"
    return opts | {"title_style_resolved": overlay.resolve_style(style, clip["id"], index),
                   "title_card": meta.get("card") or {}}


def _concat_enhancements(words_out: list[dict], duration: float, layout: str, opts: dict,
                         titles: list[str]) -> tuple[str | None, list[dict], int]:
    from . import enhance

    hook = None
    # com o cartão de título já desenhado no vídeo base, o Concat não adiciona outro texto por cima
    if opts.get("hook", True) and opts.get("title_style_resolved", "nenhum") == "nenhum":
        hook = enhance.theme_text(titles)
    zooms = []
    # no layout dividido o zoom cortaria os dois rostos; fica desligado
    if opts.get("zoom", True) and layout != "split":
        zooms = enhance.pick_zooms(words_out, duration, skip_start=enhance.HOOK_DURATION_S if hook else 0.5)
    return hook, enhance.zoom_keyframes(zooms, duration), len(zooms)


def _render_with_concat(exe: Path, src: Path, info: dict, clip: dict, words: list[dict], opts: dict, meta: dict,
                        out_dir: Path, sub_dir: Path, work_dir: Path, ctx: JobContext) -> dict:
    from . import concat_bridge

    a, b = ctx._span
    stage = ctx.stage
    # 1) vídeo base: enquadramento + remoção de pausas, sem legenda queimada (FFmpeg)
    ctx.span(a, a + (b - a) * 0.4, stage)
    clean = render.render_clip(src, info, clip, words, opts | {"captions": False, "zoom_fx": False}, out_dir, sub_dir, work_dir, ctx,
                               variant="_clean")
    ctx.check()
    duration = clean["duration"]
    layout = clean["render_info"]["layout"]
    hook, zoom_keys, n_zooms = _concat_enhancements(clean["words_out"], duration, layout, opts, meta["titles"])
    # 2) projeto no Concat (legendas, gancho, zooms) e exportação pelo próprio Concat
    ctx.span(a + (b - a) * 0.4, a + (b - a) * 0.95, stage + " (Concat)")
    width, height = config.get("render.width"), config.get("render.height")
    partial = work_dir / f"{clip['id']}.partial.mp4"
    storage.remove_quietly(partial)
    project_dir = concat_bridge.build_project(
        exe, storage.area_dir("concat", clip["project_id"]), clip["id"], Path(clean["output_path"]),
        clean["words_out"], opts.get("caption_style", "classic"), clean["render_info"]["fps"], width, height,
        hook=hook, zoom_keys=zoom_keys, export_to=partial, ctx=ctx)
    # 3) verificação, miniatura
    ctx.span(a + (b - a) * 0.95, b, stage)
    verified = ffmpeg.verify_output(partial, duration, width, height,
                                    decode=bool(config.get("render.verify_decode")), ctx=ctx)
    final = out_dir / f"{clip['id']}.mp4"
    partial.replace(final)
    thumb = out_dir / f"{clip['id']}.jpg"
    try:
        ffmpeg.thumbnail(final, thumb, at=min(1.5, duration / 2))
    except PipelineError:
        thumb = None
    ctx.progress(1.0)
    return {
        "output_path": str(final), "thumb_path": str(thumb) if thumb else None, "srt_path": clean["srt_path"],
        "duration": verified["duration"], "size_bytes": final.stat().st_size, "words_out": clean["words_out"],
        "render_info": clean["render_info"] | {"engine": "concat", "zooms": n_zooms, "hook": hook,
                                               "concat_project": str(project_dir),
                                               "concat_video": clean["output_path"]},
    }


def run_render(pid: str, clip_ids: list[str] | None, ctx: JobContext) -> dict:
    p = _project(pid)
    opts = p["options"] or {}
    src = storage.ensure_inside_root(p["source_path"])
    if not src.exists():
        raise FatalPipelineError("Arquivo de origem não encontrado (foi apagado?)")
    info = ffmpeg.probe(src).as_dict()
    transcript = transcribe.load(transcript_path(pid))
    all_words = transcribe.all_words(transcript)

    if clip_ids:
        marks = ",".join("?" * len(clip_ids))
        clips = db.fetch_all(f"SELECT * FROM clips WHERE project_id = ? AND id IN ({marks}) ORDER BY start",
                             (pid, *clip_ids))
    else:
        clips = db.fetch_all("SELECT * FROM clips WHERE project_id = ? AND selected = 1 ORDER BY start", (pid,))
    if not clips:
        raise FatalPipelineError("Nenhum corte selecionado para renderizar")

    db.update("projects", pid, status="rendering")
    out_dir = storage.area_dir("exports", pid)
    sub_dir = storage.area_dir("subtitles", pid)
    work_dir = storage.area_dir("clips", pid)
    done, failed = 0, 0
    n = len(clips)
    # posição fixa de cada corte no projeto (o estilo "variar" não muda ao refazer só um corte)
    order = [c["id"] for c in db.fetch_all(
        "SELECT id FROM clips WHERE project_id = ? AND (selected = 1 OR status = 'done') ORDER BY start", (pid,))]
    for i, clip in enumerate(clips):
        ctx.check()
        ctx.span(i / n, (i + 1) / n, f"Renderizando corte {i + 1} de {n}")
        db.update("clips", clip["id"], status="rendering", error=None)
        words = clip["words"] or render.words_for_clip(all_words, clip["start"], clip["end"])
        last_exc: Exception | None = None
        text = " ".join(w["text"] for w in words)
        meta = metadata.generate(text, p["source_title"] or p["name"], clip["category"])
        if opts.get("censor", "nenhum") != "nenhum":
            meta = censor.censor_meta(meta)  # palavrões mascarados também nos títulos e na descrição
        clip_opts = _clip_options(opts, meta, clip, order.index(clip["id"]) if clip["id"] in order else i)
        clip_opts |= _hook_options(clip, words, opts, ctx)
        for attempt in range(2):
            try:
                result = _render_one(src, info, clip, words, clip_opts, meta, out_dir, sub_dir, work_dir, ctx)
                db.update("clips", clip["id"], status="done", output_path=result["output_path"],
                          thumb_path=result["thumb_path"], srt_path=result["srt_path"],
                          duration=result["duration"], size_bytes=result["size_bytes"],
                          render_info_json=result["render_info"] | {"metadata_engine": meta["engine"],
                                                                     "short_text": meta["short_text"]},
                          titles_json=meta["titles"], description=meta["description"],
                          hashtags_json=meta["hashtags"], keywords_json=meta["keywords"],
                          rendered_at=db.now(), error=None)
                ctx.log.info("Corte %s pronto (%.1fs, layout %s, motor %s)", clip["id"], result["duration"],
                             result["render_info"]["layout"], result["render_info"].get("engine", "ffmpeg"))
                done += 1
                last_exc = None
                break
            except Cancelled:
                db.update("clips", clip["id"], status="selected" if clip["selected"] else "candidate")
                raise
            except PipelineError as exc:
                last_exc = exc
                ctx.log.warning("Falha ao renderizar %s (tentativa %d): %s", clip["id"], attempt + 1, exc)
                if not exc.retryable:
                    break
        if last_exc is not None:
            failed += 1
            db.update("clips", clip["id"], status="failed", error=str(last_exc)[:1000])
        for f in work_dir.glob(f"{clip['id']}.partial.*"):
            storage.remove_quietly(f)
    if done == 0:
        raise FatalPipelineError(f"Nenhum corte foi renderizado ({failed} falharam). Veja o log do projeto.")
    return {"done": done, "failed": failed}


def cleanup_work_dir(pid: str) -> None:
    d = storage.area_dir("clips", pid, create=False)
    if d.exists():
        for f in d.glob("*.partial.*"):
            storage.remove_quietly(f)


def copy_upload(src_tmp: Path, pid: str, ext: str) -> Path:
    dst = storage.area_dir("downloads", pid) / f"source{ext}"
    shutil.move(str(src_tmp), dst)
    return dst


# ================================================================ CONCAT
def run_concat_export(pid: str, clip_id: str, ctx: JobContext) -> str:
    """Gera uma versão sem legenda do corte e monta um projeto editável no Concat."""
    from . import concat_bridge

    exe = concat_bridge.find_executable()
    if not exe:
        raise FatalPipelineError("Concat não encontrado. Instale o Concat ou informe o caminho em Configurações.")
    p = _project(pid)
    opts = p["options"] or {}
    clip = db.fetch_one("SELECT * FROM clips WHERE id = ? AND project_id = ?", (clip_id, pid))
    if not clip:
        raise FatalPipelineError("Corte não encontrado")
    src = storage.ensure_inside_root(p["source_path"])
    info = ffmpeg.probe(src).as_dict()
    words = clip["words"] or render.words_for_clip(transcribe.all_words(transcribe.load(transcript_path(pid))),
                                                   clip["start"], clip["end"])

    ctx.span(0.0, 0.75, "Preparando vídeo sem legenda para o Concat")
    clean = render.render_clip(src, info, clip, words,
                               opts | {"captions": False, "zoom_fx": False} | _hook_options(clip, words, opts, ctx),
                               storage.area_dir("exports", pid), storage.area_dir("subtitles", pid),
                               storage.area_dir("clips", pid), ctx, variant="_clean")
    ctx.check()
    ctx.span(0.75, 1.0, "Criando projeto no Concat")
    meta = {"titles": clip["titles"]} if clip["titles"] else metadata.generate(
        " ".join(w["text"] for w in words), p["source_title"] or p["name"], clip["category"])
    titles = meta["titles"]
    if not meta.get("card"):
        meta = meta | {"card": metadata.generate(" ".join(w["text"] for w in words),
                                                 p["source_title"] or p["name"], clip["category"]).get("card")}
    if opts.get("censor", "nenhum") != "nenhum":
        meta = censor.censor_meta(meta)
    opts = _clip_options(opts, meta, clip, None)
    hook, zoom_keys, _ = _concat_enhancements(clean["words_out"], clean["duration"],
                                              clean["render_info"]["layout"], opts, titles)
    project_dir = concat_bridge.build_project(
        exe, storage.area_dir("concat", pid), clip_id, Path(clean["output_path"]), clean["words_out"],
        opts.get("caption_style", "classic"), clean["render_info"]["fps"],
        config.get("render.width"), config.get("render.height"), hook=hook, zoom_keys=zoom_keys)
    current = db.fetch_one("SELECT render_info_json FROM clips WHERE id = ?", (clip_id,))["render_info"] or {}
    db.update("clips", clip_id, render_info_json=current | {"concat_project": str(project_dir),
                                                            "concat_video": clean["output_path"]})
    ctx.log.info("Projeto do Concat criado em %s", project_dir)
    ctx.progress(1.0)
    return str(project_dir)
