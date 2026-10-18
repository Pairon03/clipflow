"""Ponte com o editor Concat: protocolo MCP (servidor falso) e, se disponível, o Concat real."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from app import config, db, storage
from app.pipeline import concat_bridge
from app.pipeline.transcribe import _split_words

HERE = Path(__file__).parent


@pytest.fixture
def fake_concat(tmp_path, monkeypatch):
    """Um 'executável' chamado concat-mcp que roda o servidor MCP falso."""
    log = tmp_path / "calls.jsonl"
    if sys.platform == "win32":
        exe = tmp_path / "concat-mcp.bat"
        exe.write_text(f'@"{sys.executable}" "{HERE / "fake_concat_mcp.py"}"\n')
    else:
        exe = tmp_path / "concat-mcp"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_concat_mcp.py"}"\n')
        exe.chmod(0o755)
    monkeypatch.setenv("FAKE_CONCAT_LOG", str(log))
    config.set_override("concat.path", str(exe))
    yield exe, log
    config.set_override("concat.path", "")


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_executable_validation(tmp_path):
    other = tmp_path / "calc.exe"
    other.write_text("x")
    assert not concat_bridge.valid_executable(other)
    with pytest.raises(ValueError):
        config.coerce("concat.path", str(other))
    good = tmp_path / "concat.exe"
    good.write_text("x")
    assert concat_bridge.valid_executable(good)
    assert concat_bridge.command(good)[1:] == ["--mcp", "headless"]
    assert concat_bridge.command(tmp_path / "concat-mcp")[1:] == ["headless"]


def test_caption_entries_are_editable_blocks():
    words = _split_words("Você sabia que o segredo é a constância? Funciona sempre.", 0.5, 5.0)
    entries = concat_bridge.caption_entries(words, "impact")
    assert entries and all(e["end"] > e["start"] for e in entries)
    assert all(a["end"] <= b["start"] for a, b in zip(entries, entries[1:]))
    assert entries[0]["text"] == entries[0]["text"].upper()  # Impact usa caixa alta
    assert " ".join(e["text"] for e in entries).replace("?", "").startswith("VOCÊ SABIA")


def test_build_project_with_fake_server(fake_concat, tmp_path):
    exe, log = fake_concat
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 2048)
    words = _split_words("um dois três quatro cinco seis", 0.2, 3.0)
    out = concat_bridge.build_project(exe, tmp_path / "proj", "abc", video, words, "classic", 30, 1080, 1920)
    assert out.is_dir()
    seq = [c["tool"] for c in calls(log)]
    assert seq == ["project_create", "media_import", "clips_add_sequence", "captions_add", "project_save",
                   "project_close"]
    create = calls(log)[0]["args"]
    assert create["video"] == {"width": 1080, "height": 1920, "rateNum": 30, "rateDen": 1}
    caps = calls(log)[3]["args"]["captions"]
    assert caps[0]["start"] == pytest.approx(0.2, abs=0.01)
    # recriar apaga o projeto antigo em vez de falhar
    concat_bridge.build_project(exe, tmp_path / "proj", "abc", video, words, "classic", 30, 1080, 1920)


def test_error_from_concat_is_reported(fake_concat, tmp_path):
    exe, _ = fake_concat
    with pytest.raises(concat_bridge.McpError, match="recusou 'media_import'"):
        concat_bridge.build_project(exe, tmp_path / "p", "x", tmp_path / "nao-existe.mp4", [], "classic",
                                    30, 1080, 1920)


def test_concat_export_end_to_end_api(fake_concat, sample_two):
    """Fluxo pela API: Short → 'Editar no Concat' → vídeo sem legenda + projeto criado."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from test_api_e2e import create, wait

    with TestClient(create_app(start_worker=True)) as client:
        assert client.get("/api/meta").json()["concat_available"] is True
        pid = create(client, sample_two, force=True).json()["id"]
        p = wait(client, pid)
        clip = next(c for c in p["clips"] if c["status"] == "done")
        assert client.post(f"/api/clips/{clip['id']}/concat").status_code == 200
        p = wait(client, pid, ("completed", "failed"))
        for _ in range(100):
            job = db.fetch_one("SELECT * FROM jobs WHERE project_id = ? ORDER BY id DESC LIMIT 1", (pid,))
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        assert job["kind"] == "concat" and job["status"] == "done", job["error"]
        c = db.fetch_one("SELECT * FROM clips WHERE id = ?", (clip["id"],))
        info = c["render_info"]
        assert Path(info["concat_project"]).is_dir()
        assert Path(info["concat_project"]).is_relative_to(storage.root() / "concat" / pid)
        clean = Path(info["concat_video"])
        assert clean.name == f"{clip['id']}_clean.mp4" and clean.is_file()
        assert Path(c["output_path"]).is_file()  # o Short com legenda continua intacto
        sent = calls(fake_concat[1])
        assert any(x["tool"] == "captions_add" and x["args"]["captions"] for x in sent)
        # apagar o projeto remove também a pasta do Concat
        client.delete(f"/api/projects/{pid}")
        assert not (storage.root() / "concat" / pid).exists()


REAL = os.environ.get("CLIPFLOW_TEST_CONCAT")


@pytest.mark.skipif(not REAL, reason="defina CLIPFLOW_TEST_CONCAT com o caminho do concat/concat-mcp real")
def test_real_concat(sample_two, tmp_path):
    exe = Path(REAL)
    roots_ok = tmp_path.resolve()
    config.set_override("storage.data_dir", str(roots_ok))
    config.set_override("concat.path", str(exe))
    try:
        st = concat_bridge.status()
        assert st["available"] and st.get("version"), st
        words = _split_words("Você sabia que o segredo é a constância?", 0.5, 4.0)
        out = concat_bridge.build_project(exe, tmp_path / "proj", "real", sample_two["video"], words,
                                          "classic", 12, 1080, 1920)
        assert out.is_dir() and any(out.iterdir())
        with concat_bridge.ConcatClient(exe, [tmp_path]) as c:
            c.initialize()
            c.call("project_open", {"path": str(out)})
            tl = c.call("timeline_read", {"path": str(out)})
        text = json.dumps(tl)
        assert "constância" in text or "CONSTÂNCIA" in text or "segredo" in text, text[:2000]
    finally:
        config.reload()
