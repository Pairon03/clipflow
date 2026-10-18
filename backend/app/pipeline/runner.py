"""Orquestração das etapas: análise (obter → transcrever → selecionar) e renderização."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from .. import config, db, storage
from . import audio as audio_mod
from . import ffmpeg, llm, metadata, render, selection, transcribe, youtube
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
    return [c.as_dict() for c in chosen]


# ================================================================ RENDER
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
    for i, clip in enumerate(clips):
        ctx.check()
        ctx.span(i / n, (i + 1) / n, f"Renderizando corte {i + 1} de {n}")
        db.update("clips", clip["id"], status="rendering", error=None)
        words = clip["words"] or render.words_for_clip(all_words, clip["start"], clip["end"])
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                result = render.render_clip(src, info, clip, words, opts, out_dir, sub_dir, work_dir, ctx)
                text = " ".join(w["text"] for w in words)
                meta = metadata.generate(text, p["source_title"] or p["name"], clip["category"])
                db.update("clips", clip["id"], status="done", output_path=result["output_path"],
                          thumb_path=result["thumb_path"], srt_path=result["srt_path"],
                          duration=result["duration"], size_bytes=result["size_bytes"],
                          render_info_json=result["render_info"] | {"metadata_engine": meta["engine"],
                                                                     "short_text": meta["short_text"]},
                          titles_json=meta["titles"], description=meta["description"],
                          hashtags_json=meta["hashtags"], keywords_json=meta["keywords"],
                          rendered_at=db.now(), error=None)
                ctx.log.info("Corte %s pronto (%.1fs, layout %s)", clip["id"], result["duration"],
                             result["render_info"]["layout"])
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
    clean = render.render_clip(src, info, clip, words, opts | {"captions": False},
                               storage.area_dir("exports", pid), storage.area_dir("subtitles", pid),
                               storage.area_dir("clips", pid), ctx, variant="_clean")
    ctx.check()
    ctx.span(0.75, 1.0, "Criando projeto no Concat")
    project_dir = concat_bridge.build_project(
        exe, storage.area_dir("concat", pid), clip_id, Path(clean["output_path"]), clean["words_out"],
        opts.get("caption_style", "classic"), clean["render_info"]["fps"],
        config.get("render.width"), config.get("render.height"))
    current = db.fetch_one("SELECT render_info_json FROM clips WHERE id = ?", (clip_id,))["render_info"] or {}
    db.update("clips", clip_id, render_info_json=current | {"concat_project": str(project_dir),
                                                            "concat_video": clean["output_path"]})
    ctx.log.info("Projeto do Concat criado em %s", project_dir)
    ctx.progress(1.0)
    return str(project_dir)
