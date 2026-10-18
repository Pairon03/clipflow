"""Aplicação FastAPI do ClipFlow Studio.

Execute com:  python -m app   (dentro da pasta backend)
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, storage
from .api import clips, projects, system, uploads
from .worker import worker

log = logging.getLogger("clipflow")
FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    removed = uploads.cleanup_expired()
    for f in (storage.root() / "tmp").glob("*.zip"):
        storage.remove_quietly(f)
    if removed:
        log.info("%d upload(s) expirado(s) removido(s)", removed)
    if app.state.start_worker:
        worker.start()
    log.info("ClipFlow Studio pronto. Dados em %s", storage.root())
    yield
    if app.state.start_worker:
        worker.stop()


def create_app(start_worker: bool = True) -> FastAPI:
    app = FastAPI(title="ClipFlow Studio", version="0.1.0", lifespan=lifespan)
    app.state.start_worker = start_worker

    @app.middleware("http")
    async def auth_and_headers(request: Request, call_next):
        token = config.get("server.access_token")
        path = request.url.path
        if token and path.startswith("/api/") and path != "/api/health":
            given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            given = given or request.query_params.get("token", "")
            if not hmac.compare_digest(given.encode(), token.encode()):
                return JSONResponse({"detail": "Token de acesso inválido"}, status_code=401)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(storage.UnsafePathError)
    async def unsafe_path(_request: Request, exc: storage.UnsafePathError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.include_router(system.router)
    app.include_router(uploads.router)
    app.include_router(projects.router)
    app.include_router(clips.router)

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Não encontrado"}, status_code=404)
            candidate = storage.safe_join(FRONTEND_DIST, full_path) if full_path else FRONTEND_DIST
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return JSONResponse({"detail": "Interface não compilada. Rode 'npm run build' na pasta frontend "
                                           "ou use o modo de desenvolvimento (npm run dev)."})
    return app


app = create_app()
