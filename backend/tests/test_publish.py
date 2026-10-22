"""Publicação no YouTube contra um servidor falso do Google (OAuth com PKCE, envio retomável, cota, revogação)."""
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app import db, publisher, storage, youtube_api
from app.main import create_app
from fake_google import FakeGoogle
from fastapi.testclient import TestClient

CLIENT_JSON = {"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-x",
                             "project_id": "clipflow-teste"}}


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(youtube_api, "AUTH_URL", fake.base + "/auth")
    monkeypatch.setattr(youtube_api, "TOKEN_URL", fake.base + "/token")
    monkeypatch.setattr(youtube_api, "REVOKE_URL", fake.base + "/revoke")
    monkeypatch.setattr(youtube_api, "API_URL", fake.base + "/youtube/v3")
    monkeypatch.setattr(youtube_api, "UPLOAD_URL", fake.base + "/upload")
    monkeypatch.setattr(youtube_api, "CHUNK", 256 * 1024)
    youtube_api.remove_client()
    db.execute("DELETE FROM publications")
    yield fake
    youtube_api.remove_client()
    fake.close()


@pytest.fixture()
def client():
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def _clip(size=700_000, **extra) -> dict:
    """Projeto + corte renderizado com um arquivo de vídeo falso."""
    pid, cid = db.new_id(), db.new_id()
    now = db.now()
    db.execute("INSERT INTO projects (id, name, status, source_type, source_title, rights_basis, rights_confirmed_at, "
               "created_at, updated_at) VALUES (?, 'Teste', 'completed', 'upload', 'Fulano - Podcast #1', 'own', ?, ?, ?)",
               (pid, now, now, now))
    out = storage.area_dir("exports", pid) / f"{cid}.mp4"
    out.write_bytes(bytes(range(256)) * (size // 256) + b"x" * (size % 256))
    fields = {"titles_json": json.dumps(["Ele contou <tudo> sobre a falência", "Outro título"]),
              "description": "🎯 Ele responde\n\n#shorts #cortes", "hashtags_json": json.dumps(["#shorts", "#cortes"]),
              "keywords_json": json.dumps(["falência", "dinheiro", "empresa"])} | extra
    db.execute("INSERT INTO clips (id, project_id, start, end, status, output_path, titles_json, description, "
               "hashtags_json, keywords_json, created_at) VALUES (?, ?, 0, 40, 'done', ?, ?, ?, ?, ?, ?)",
               (cid, pid, str(out), fields["titles_json"], fields["description"], fields["hashtags_json"],
                fields["keywords_json"], now))
    return db.fetch_one("SELECT * FROM clips WHERE id = ?", (cid,))


def _connect(google, client) -> None:
    r = client.put("/api/youtube/client", content=json.dumps(CLIENT_JSON).encode())
    assert r.status_code == 200 and r.json()["has_client"] and not r.json()["connected"]
    url = client.post("/api/youtube/connect").json()["url"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    assert q["redirect_uri"].startswith("http://127.0.0.1:") and "youtube.upload" in q["scope"]
    google.challenges["code-abc"] = q["code_challenge"]
    r = client.get(f"/?state={q['state']}&code=code-abc", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/publicar?youtube=ok"


def test_client_secret_validation(google, client):
    web = {"web": {"client_id": "x.apps.googleusercontent.com", "client_secret": "y"}}
    r = client.put("/api/youtube/client", content=json.dumps(web).encode())
    assert r.status_code == 422 and "App para computador" in r.json()["detail"]
    assert client.put("/api/youtube/client", content=b"nada").status_code == 422
    assert client.put("/api/youtube/client", content=json.dumps(CLIENT_JSON).encode()).status_code == 200
    acc = client.get("/api/youtube/account").json()
    assert acc["has_client"] and acc["project_id"] == "clipflow-teste" and "client_secret" not in json.dumps(acc)
    assert acc["defaults"]["times"] == ["12:00", "19:00"]


def test_oauth_flow_connects_channel_and_never_exposes_token(google, client):
    _connect(google, client)
    acc = client.get("/api/youtube/account").json()
    assert acc["connected"] and acc["channel"]["title"] == "Meu Canal de Cortes"
    assert "rt-1" not in json.dumps(acc) and "at-1" not in json.dumps(acc)
    assert google.token_calls[0]["code_verifier"]                       # PKCE enviado
    # state usado não vale de novo; state desconhecido não é tratado como retorno do Google
    r = client.get("/?state=outro&code=code-abc", follow_redirects=False)
    assert r.status_code != 303
    assert client.post("/api/youtube/disconnect").json()["connected"] is False


def test_oauth_denied_returns_message(google, client):
    client.put("/api/youtube/client", content=json.dumps(CLIENT_JSON).encode())
    url = client.post("/api/youtube/connect").json()["url"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    r = client.get(f"/?state={state}&error=access_denied", follow_redirects=False)
    assert r.status_code == 303 and "youtube=erro" in r.headers["location"]
    assert not youtube_api.status()["connected"]


def test_publish_scheduled_upload_end_to_end(google, client):
    _connect(google, client)
    clip = _clip()
    when = time.time() + 2 * 3600
    r = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": clip["titles"][0],
                                                             "publish_at": when}], "privacy": "private"})
    assert r.status_code == 200, r.text
    pub_id = r.json()["created"][0]["id"]
    assert publisher.publisher.run_next()
    pub = publisher.get(pub_id)
    assert pub["status"] == "scheduled" and pub["video_id"] == "vid-1" and pub["url"].endswith("/shorts/vid-1")
    up = google.uploads[0]
    assert up["data"] == Path(clip["output_path"]).read_bytes()       # arquivo chegou inteiro, em partes
    assert google.chunks == 3                                           # 700 kB em partes de 256 KiB
    sn, st = up["meta"]["snippet"], up["meta"]["status"]
    assert sn["title"] == "Ele contou tudo sobre a falência"           # < > removidos
    assert sn["tags"][:3] == ["shorts", "cortes", "falência"] and sn["categoryId"] == "24"
    assert st["privacyStatus"] == "private" and st["selfDeclaredMadeForKids"] is False
    assert abs(datetime.fromisoformat(st["publishAt"].replace("Z", "+00:00")).timestamp() - when) < 1
    assert up["query"]["notifySubscribers"] == "true"
    # o mesmo corte não entra duas vezes sem pedir
    again = {"items": [{"clip_id": clip["id"], "title": "x"}]}
    assert client.post("/api/publish/youtube", json=again).status_code == 409
    assert client.post("/api/publish/youtube", json=again | {"again": True}).status_code == 200
    listed = client.get("/api/publications").json()
    assert {p["status"] for p in listed} == {"scheduled", "queued"} and "session_url" not in listed[0]


def test_upload_resumes_after_connection_error(google, client):
    _connect(google, client)
    clip = _clip(size=900_000)
    google.fail_chunk_once = 2
    pub_id = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "Título"}],
                                                       "privacy": "unlisted"}).json()["created"][0]["id"]
    publisher.publisher.run_next()
    pub = publisher.get(pub_id)
    assert pub["status"] == "queued" and pub["run_after"] > time.time() and "nova tentativa" in pub["error"]
    assert pub["bytes_sent"] == 256 * 1024                              # 1ª parte confirmada
    db.update("publications", pub_id, run_after=0)
    publisher.publisher.run_next()
    pub = publisher.get(pub_id)
    assert pub["status"] == "done" and len(google.sessions) == 1        # mesma sessão, sem reenviar do zero
    assert google.uploads[0]["data"] == Path(clip["output_path"]).read_bytes()
    assert google.uploads[0]["meta"]["status"]["privacyStatus"] == "unlisted"


def test_quota_exceeded_waits_until_reset(google, client):
    _connect(google, client)
    clip = _clip()
    google.quota_exceeded = True
    pub_id = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "T"}]}
                         ).json()["created"][0]["id"]
    publisher.publisher.run_next()
    pub = publisher.get(pub_id)
    assert pub["status"] == "waiting_quota" and pub["attempts"] == 0
    reset = datetime.fromtimestamp(pub["run_after"], timezone.utc)
    assert (reset.hour, reset.minute) == (8, 5) and 0 < pub["run_after"] - time.time() <= 86400
    assert not publisher.publisher.run_next()                           # não insiste antes da hora


def test_revoked_authorization_pauses_queue(google, client):
    _connect(google, client)
    clip = _clip()
    tok = youtube_api.token() | {"expires_at": 0}                       # força renovar o token
    youtube_api._write_private(youtube_api.token_path(), tok)
    google.revoked = True
    pub_id = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "T"}]}
                         ).json()["created"][0]["id"]
    publisher.publisher.run_next()
    assert publisher.get(pub_id)["status"] == "queued"                  # espera, não falha
    st = client.get("/api/youtube/account").json()
    assert st["needs_reconnect"] and not st["connected"]
    assert not publisher.publisher.run_next()                           # nada sobe até reconectar


def test_cancel_retry_and_validation(google, client):
    clip = _clip()
    r = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "T",
                                                             "publish_at": time.time() + 60}]})
    assert r.status_code == 422                                         # agendamento muito em cima
    assert client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "T"}],
                                                     "privacy": "secreto"}).status_code == 422
    pub_id = client.post("/api/publish/youtube", json={"items": [{"clip_id": clip["id"], "title": "T"}]}
                         ).json()["created"][0]["id"]
    assert not publisher.publisher.run_next()                           # conta não conectada: fica na fila
    assert client.post(f"/api/publications/{pub_id}/cancel").json()["ok"]
    assert publisher.get(pub_id)["status"] == "cancelled"
    assert client.post(f"/api/publications/{pub_id}/retry").json()["ok"]
    assert publisher.get(pub_id)["status"] == "queued"
    assert client.delete(f"/api/publications/{pub_id}").status_code == 409


def test_text_rules_and_tiktok_caption(client):
    assert publisher.clean_title("  A <b>   história  ") == "A b história"
    assert len(publisher.clean_title("x" * 300)) == 100
    assert len(publisher.clean_description("ç" * 4000).encode()) <= 5000
    tags = publisher.build_tags(["#shorts", "#Shorts", "#cortes"], ["tag com espaço"] + [f"palavra{i}" for i in range(80)])
    assert tags[:3] == ["shorts", "cortes", "tag com espaço"]
    assert sum(len(t) + (2 if " " in t else 0) for t in tags) + len(tags) - 1 <= 500
    meta, note = publisher.video_metadata({"title": "T", "description": "", "tags": [], "category_id": "24",
                                           "privacy": "private", "publish_at": time.time() - 10})
    assert meta["status"]["privacyStatus"] == "public" and "publishAt" not in meta["status"] and note
    clip = _clip()
    cap = client.get(f"/api/clips/{clip['id']}/tiktok-caption?title=1").json()["caption"]
    assert cap.startswith("Outro título\n\n🎯 Ele responde") and cap.endswith("#shorts #cortes")
