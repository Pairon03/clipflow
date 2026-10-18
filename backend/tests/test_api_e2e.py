"""Testes de ponta a ponta: API HTTP + fila + pipeline real (FFmpeg, detecção de rostos, legendas)."""
import io
import json
import resource
import time
import wave
import zipfile
from pathlib import Path

import numpy as np
import pysubs2
import pytest
from fastapi.testclient import TestClient

from app import config, db, storage
from app.main import create_app
from app.pipeline import ffmpeg, render, runner
from app.pipeline.errors import FatalPipelineError, PipelineError


@pytest.fixture(scope="module")
def client():
    app = create_app(start_worker=True)
    with TestClient(app) as c:
        yield c


def upload(client, path: Path, name: str | None = None, kind="video"):
    r = client.put(f"/api/uploads/{kind}", content=path.read_bytes(),
                   headers={"X-Filename": name or path.name})
    return r


def wait(client, pid, statuses=("completed", "failed", "awaiting_review", "cancelled"), timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/projects/{pid}").json()
        if p["status"] in statuses:
            return p
        time.sleep(0.5)
    raise AssertionError(f"timeout: {p['status']} {p['stage']}")


def create(client, sample, options=None, force=False, rights=None):
    v = upload(client, sample["video"]).json()
    s = upload(client, sample["srt"], kind="subtitle").json()
    body = {"source": {"type": "upload", "upload_id": v["token"]}, "subtitle_upload_id": s["token"],
            "rights": rights or {"confirmed": True, "basis": "own", "note": ""},
            "options": options or {"count": 2, "min_duration": 15, "max_duration": 30}, "force": force}
    return client.post("/api/projects", json=body)


def test_full_pipeline_upload_to_shorts(client, sample_two):
    r = create(client, sample_two, {"count": 2, "min_duration": 15, "max_duration": 30, "caption_style": "impact"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    p = wait(client, pid)
    assert p["status"] == "completed", p.get("error")
    done = [c for c in p["clips"] if c["status"] == "done"]
    assert len(done) == 2

    # arquivos organizados por projeto
    root = storage.root()
    for area in ("projects", "downloads", "transcripts", "subtitles", "exports"):
        assert (root / area / pid).is_dir()
    assert (root / "logs" / f"{pid}.log").exists()
    meta = json.loads((root / "projects" / pid / "project.json").read_text(encoding="utf-8"))
    assert meta["rights"]["basis"] == "own" and meta["source"]["source_type"] == "upload"
    assert not (root / "transcripts" / pid / "audio.wav").exists()  # temporário removido

    for c in done:
        assert c["titles"] and 1 <= len(c["titles"]) <= 3
        assert "#shorts" in c["hashtags"]
        # vídeo final reproduzível
        v = client.get(f"/api/clips/{c['id']}/video")
        assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
        # suporte a Range (necessário para o player do navegador)
        part = client.get(f"/api/clips/{c['id']}/video", headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100
        assert client.get(f"/api/clips/{c['id']}/thumb").status_code == 200
        srt = client.get(f"/api/clips/{c['id']}/srt")
        assert srt.status_code == 200 and "-->" in srt.text

    # ZIP do projeto
    z = client.get(f"/api/projects/{pid}/zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert sum(n.endswith(".mp4") for n in names) == 2 and any(n.startswith("LEIA-ME") for n in names)

    lib = client.get("/api/library").json()
    assert {c["id"] for c in done} <= {c["id"] for c in lib}
    dash = client.get("/api/dashboard").json()
    assert dash["shorts_total"] >= 2 and dash["projects_completed"] >= 1
    assert client.get(f"/api/projects/{pid}/transcript.srt").status_code == 200


def test_caption_sync_matches_speech(client, sample_two, tmp_path):
    """A primeira palavra de cada bloco de legenda deve coincidir com fala no áudio do vídeo final."""
    clips = db.fetch_all("SELECT * FROM clips WHERE status = 'done' ORDER BY rowid")
    c, ass = next((c, a) for c in clips
                  if (a := storage.area_dir("subtitles", c["project_id"]) / f"{c['id']}.ass").is_file())
    subs = pysubs2.load(str(ass))
    wav = tmp_path / "out.wav"
    ffmpeg.extract_audio(Path(c["output_path"]), wav)
    with wave.open(str(wav)) as wf:
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    sr = 16000

    def rms(t0, t1):
        seg = x[int(t0 * sr):int(t1 * sr)]
        return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0

    # início de cada bloco (CaptionLow = legenda deslocada para baixo do título)
    starts = [e.start / 1000 for e in subs if "\\fad" in e.text and e.style in ("Caption", "CaptionLow")]
    assert len(starts) >= 3
    voiced = [rms(t, t + 0.25) > 0.01 for t in starts]
    assert sum(voiced) / len(voiced) >= 0.9, voiced
    # e o vídeo dura o mesmo que a última legenda (sem dessincronização acumulada)
    last_end = max(e.end for e in subs) / 1000
    assert abs(last_end - c["duration"]) < 1.0


def test_duplicate_prevention(client, sample_two):
    r = create(client, sample_two)
    assert r.status_code == 409
    assert r.json()["detail"]["project_id"]
    r2 = create(client, sample_two, force=True)
    assert r2.status_code == 200
    wait(client, r2.json()["id"])


def test_input_validation(client, sample_two, tmp_path):
    assert create(client, sample_two, rights={"confirmed": False, "basis": "own"}).status_code == 422
    assert create(client, sample_two, options={"count": 999}).status_code == 422
    assert create(client, sample_two, options={"min_duration": 60, "max_duration": 30}).status_code == 422
    assert upload(client, sample_two["video"], name="virus.exe").status_code == 415
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"isto nao e um video" * 200)
    assert upload(client, fake).status_code == 422
    config.set_override("limits.max_upload_mb", 0)
    try:
        assert upload(client, sample_two["video"]).status_code == 413
    finally:
        config.set_override("limits.max_upload_mb", 4096)
    assert client.get("/api/projects/..%2F..%2Fetc").status_code in (400, 404)
    r = client.get("/..%2F..%2F..%2Fetc%2Fpasswd")  # interface SPA não serve arquivos fora da pasta
    assert "root:" not in r.text
    assert client.get("/api/clips/zzzzzzzzzzzz/video").status_code == 404
    assert client.post("/api/youtube/validate", json={"url": "https://vimeo.com/1"}).json()["valid"] is False


def test_review_edit_swap_and_render_one(client, sample_two):
    r = create(client, sample_two, {"count": 2, "min_duration": 15, "max_duration": 30, "review": True}, force=True)
    pid = r.json()["id"]
    p = wait(client, pid)
    assert p["status"] == "awaiting_review"
    sel = [c for c in p["clips"] if c["selected"]]
    alts = [c for c in p["clips"] if not c["selected"]]
    assert len(sel) == 2

    # correção de legenda
    words = client.get(f"/api/clips/{sel[0]['id']}/words").json()["words"]
    new_text = " ".join(w["text"] for w in words).replace("segredo", "SEGREDO", 1) + " (corrigido)"
    r = client.patch(f"/api/clips/{sel[0]['id']}", json={"text": new_text})
    assert r.status_code == 200 and r.json()["edited_words"]
    # ajuste de intervalo
    r = client.patch(f"/api/clips/{sel[1]['id']}", json={"start": sel[1]["start"] + 0.2})
    assert r.status_code == 200
    assert client.patch(f"/api/clips/{sel[1]['id']}", json={"start": 0, "end": 1}).status_code == 422
    # substituição por alternativa
    if alts:
        assert client.post(f"/api/clips/{sel[1]['id']}/swap", json={"with_id": alts[0]["id"]}).status_code == 200
    # refazer seleção (rápido, usa transcrição existente)
    # renderiza só o primeiro
    r = client.post(f"/api/projects/{pid}/render", json={"clip_ids": [sel[0]["id"]]})
    assert r.status_code == 200
    p = wait(client, pid, ("completed", "failed"))
    assert p["status"] == "completed"
    done = [c for c in p["clips"] if c["status"] == "done"]
    assert [c["id"] for c in done] == [sel[0]["id"]]
    ass = (storage.area_dir("subtitles", pid) / f"{sel[0]['id']}.ass").read_text(encoding="utf-8")
    assert "SEGREDO" in ass and "(corrigido)" in ass

    r = client.post(f"/api/projects/{pid}/reselect", json={"count": 3, "min_duration": 10, "max_duration": 20})
    assert r.status_code == 200
    assert sum(1 for c in r.json()["clips"] if c["selected"]) == 3


def test_cancel_during_render(client, sample_two, monkeypatch):
    original = render.render_clip

    def slow_render(src, info, clip, words, options, out_dir, sub_dir, work_dir, ctx):
        for _ in range(200):
            ctx.check()
            time.sleep(0.05)
        return original(src, info, clip, words, options, out_dir, sub_dir, work_dir, ctx)

    monkeypatch.setattr(render, "render_clip", slow_render)
    pid = create(client, sample_two, force=True).json()["id"]
    wait(client, pid, ("rendering",), timeout=60)
    assert client.post(f"/api/projects/{pid}/cancel").status_code == 200
    p = wait(client, pid, ("cancelled",), timeout=30)
    assert p["status"] == "cancelled"
    assert client.post(f"/api/projects/{pid}/cancel").status_code == 409
    monkeypatch.setattr(render, "render_clip", original)
    # retomada após cancelamento
    assert client.post(f"/api/projects/{pid}/retry").json()["kind"] == "render"
    assert wait(client, pid)["status"] == "completed"


def test_retry_on_transient_error(client, sample_two, monkeypatch):
    calls = {"n": 0}
    original = runner.run_analysis

    def flaky(pid, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PipelineError("falha temporária simulada")
        return original(pid, ctx)

    monkeypatch.setattr(runner, "run_analysis", flaky)
    pid = create(client, sample_two, force=True).json()["id"]
    p = wait(client, pid, ("completed", "failed"), timeout=120)
    assert p["status"] == "completed" and calls["n"] == 2
    log = client.get(f"/api/projects/{pid}/log").text
    assert "falha temporária simulada" in log


def test_fatal_error_is_reported_without_retry(client, sample_two, monkeypatch):
    calls = {"n": 0}

    def broken(pid, ctx):
        calls["n"] += 1
        raise FatalPipelineError("Arquivo de vídeo inválido (simulado)")

    monkeypatch.setattr(runner, "run_analysis", broken)
    pid = create(client, sample_two, force=True).json()["id"]
    p = wait(client, pid, ("failed",), timeout=60)
    assert "simulado" in p["error"] and calls["n"] == 1


def test_queue_recovers_running_jobs_after_restart(client, sample_two):
    """Simula queda do servidor: tarefa ficou 'running' e deve ser retomada pela fila."""
    from app.worker import Worker, worker

    pid = create(client, sample_two, force=True).json()["id"]
    wait(client, pid)
    worker.stop()
    db.update("projects", pid, status="rendering")
    db.execute("INSERT INTO jobs (project_id, kind, payload_json, status, max_attempts, created_at, attempts) "
               "VALUES (?, 'render', '{}', 'running', 2, ?, 0)", (pid, db.now()))
    w = Worker()
    w.start()
    try:
        p = wait(client, pid, ("completed", "failed"), timeout=120)
        for _ in range(100):
            job = db.fetch_one("SELECT * FROM jobs WHERE project_id = ? ORDER BY id DESC LIMIT 1", (pid,))
            if job["status"] != "running":
                break
            time.sleep(0.2)
        assert job["status"] == "done" and p["status"] == "completed"
    finally:
        w.stop()
        worker.start()


def test_concurrency_limit_and_batch(client, sample_two):
    """Vários projetos em lote: nunca mais tarefas simultâneas que o limite."""
    config.set_override("limits.max_concurrent_jobs", 1)
    pids = [create(client, sample_two, force=True).json()["id"] for _ in range(3)]
    max_running = 0
    t0 = time.time()
    while time.time() - t0 < 300:
        n = db.fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'running'")["n"]
        max_running = max(max_running, n)
        sts = [client.get(f"/api/projects/{p}").json()["status"] for p in pids]
        if all(s in ("completed", "failed") for s in sts):
            break
        time.sleep(0.2)
    assert sts == ["completed"] * 3
    assert max_running <= 1


def test_memory_and_storage_usage(client):
    """Registra pico de memória (processo + FFmpeg) e espaço por Short. Limites folgados para PCs modestos."""
    self_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    child_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    clips = db.fetch_all("SELECT size_bytes, duration FROM clips WHERE status = 'done'")
    mb_per_min = sum(c["size_bytes"] for c in clips) / 1048576 / (sum(c["duration"] for c in clips) / 60)
    print(f"\n[uso] pico RAM Python: {self_mb:.0f} MB | pico RAM FFmpeg: {child_mb:.0f} MB | "
          f"{mb_per_min:.1f} MB por minuto de Short | total dados: {sum(storage.usage_by_area().values()) / 1048576:.1f} MB")
    assert self_mb < 2048 and child_mb < 1536


def test_delete_project_removes_files(client, sample_two):
    pid = create(client, sample_two, force=True).json()["id"]
    wait(client, pid)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    for area in storage.AREAS:
        assert not (storage.root() / area / pid).exists()
    assert client.get(f"/api/projects/{pid}").status_code == 404
