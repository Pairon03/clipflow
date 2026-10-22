"""Servidor falso do Google (OAuth + YouTube Data API) para testar o envio sem conta real.

Segue o protocolo documentado: token com PKCE, envio retomável com 308/Range e consulta "bytes */total".
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeGoogle:
    def __init__(self) -> None:
        self.challenges: dict[str, str] = {}      # code -> code_challenge
        self.revoked = False
        self.quota_exceeded = False
        self.fail_chunk_once: int | None = None   # número da parte que falha (503) uma vez
        self.sessions: dict[str, dict] = {}
        self.uploads: list[dict] = []             # vídeos concluídos: metadados + bytes
        self.token_calls: list[dict] = []
        self.chunks = 0
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self._srv.server_port}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._srv.shutdown()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencioso
                pass

            def _send(self, code, body=None, headers=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _authed(self):
                return self.headers.get("Authorization", "").startswith("Bearer at-")

            def do_POST(self):
                url = urllib.parse.urlparse(self.path)
                body = self._body()
                if url.path == "/token":
                    f = dict(urllib.parse.parse_qsl(body.decode()))
                    fake.token_calls.append(f)
                    if f.get("grant_type") == "authorization_code":
                        challenge = fake.challenges.get(f.get("code", ""))
                        digest = base64.urlsafe_b64encode(
                            hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                        if not challenge or digest != challenge or not f.get("client_secret"):
                            return self._send(400, {"error": "invalid_grant", "error_description": "Bad code"})
                        return self._send(200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3599,
                                                "scope": "https://www.googleapis.com/auth/youtube.upload "
                                                         "https://www.googleapis.com/auth/youtube.readonly"})
                    if f.get("grant_type") == "refresh_token":
                        if fake.revoked:
                            return self._send(400, {"error": "invalid_grant", "error_description": "revoked"})
                        return self._send(200, {"access_token": "at-2", "expires_in": 3599})
                    return self._send(400, {"error": "unsupported_grant_type"})
                if url.path == "/revoke":
                    return self._send(200, {})
                if url.path == "/upload":
                    if not self._authed():
                        return self._send(401, {"error": {"code": 401, "message": "Login",
                                                          "errors": [{"reason": "authError"}]}})
                    if fake.quota_exceeded:
                        return self._send(403, {"error": {"code": 403, "message": "quota",
                                                          "errors": [{"reason": "quotaExceeded"}]}})
                    q = dict(urllib.parse.parse_qsl(url.query))
                    assert q["uploadType"] == "resumable" and q["part"] == "snippet,status"
                    sid = str(len(fake.sessions) + 1)
                    fake.sessions[sid] = {"meta": json.loads(body), "query": q, "data": bytearray(),
                                          "size": int(self.headers["X-Upload-Content-Length"])}
                    return self._send(200, None, {"Location": f"{fake.base}/session/{sid}"})
                return self._send(404, {"error": "not found"})

            def do_PUT(self):
                url = urllib.parse.urlparse(self.path)
                body = self._body()
                s = fake.sessions.get(url.path.rsplit("/", 1)[-1])
                if not url.path.startswith("/session/") or s is None:
                    return self._send(404, {"error": {"code": 404, "message": "gone"}})
                rng = self.headers.get("Content-Range", "")
                if rng.startswith("bytes */"):
                    if len(s["data"]) == s["size"]:
                        return self._send(200, {"id": "vid-" + url.path.rsplit("/", 1)[-1]})
                    h = {"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {}
                    return self._send(308, None, h)
                fake.chunks += 1
                if fake.fail_chunk_once == fake.chunks:
                    fake.fail_chunk_once = None
                    return self._send(503, {"error": {"code": 503, "message": "backend error"}})
                start = int(rng.split(" ")[1].split("-")[0])
                assert start == len(s["data"]), (start, len(s["data"]))
                s["data"] += body
                if len(s["data"]) >= s["size"]:
                    fake.uploads.append({"meta": s["meta"], "query": s["query"], "data": bytes(s["data"])})
                    return self._send(200, {"id": "vid-" + url.path.rsplit("/", 1)[-1],
                                            "status": s["meta"].get("status")})
                return self._send(308, None, {"Range": f"bytes=0-{len(s['data']) - 1}"})

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path == "/youtube/v3/channels":
                    if not self._authed():
                        return self._send(401, {"error": {"code": 401, "errors": [{"reason": "authError"}]}})
                    return self._send(200, {"items": [{"id": "UC123", "snippet": {
                        "title": "Meu Canal de Cortes", "customUrl": "@meucanal",
                        "thumbnails": {"default": {"url": "https://example.com/a.jpg"}}}}]})
                return self._send(404, {})

        return H
