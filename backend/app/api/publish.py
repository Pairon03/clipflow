"""Publicação: conexão com o YouTube, fila de envios e legenda pronta para o TikTok."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import config, db, publisher, youtube_api
from ..youtube_api import YouTubeError
from .common import get_clip_or_404

router = APIRouter(prefix="/api", tags=["publish"])


@router.get("/youtube/account")
def youtube_account():
    return youtube_api.status() | {
        "categories": publisher.CATEGORIES,
        "defaults": {"category_id": config.get("youtube.category_id"),
                     "notify": config.get("youtube.notify_subscribers"),
                     "times": config.parse_times(config.get("youtube.times"))},
    }


@router.put("/youtube/client")
async def put_youtube_client(request: Request):
    data = await request.body()
    if not data or len(data) > 64 * 1024:
        raise HTTPException(413, "Arquivo vazio ou grande demais (envie o client_secret.json)")
    try:
        youtube_api.save_client(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    youtube_api.disconnect(revoke=False)         # credencial nova: autorização antiga não vale mais
    return youtube_api.status()


@router.delete("/youtube/client")
def delete_youtube_client():
    youtube_api.remove_client()
    return youtube_api.status()


@router.post("/youtube/connect")
def youtube_connect(request: Request):
    """Devolve o endereço de autorização do Google. O retorno chega em http://127.0.0.1:<porta>/?code=…"""
    port = request.url.port or int(config.get("server.port"))
    try:
        return {"url": youtube_api.auth_url(port)}
    except YouTubeError as exc:
        raise HTTPException(422, str(exc))


@router.post("/youtube/disconnect")
def youtube_disconnect():
    youtube_api.disconnect()
    return youtube_api.status()


def oauth_callback(params: dict) -> str:
    """Trata o retorno do Google (chamado pelo app principal na rota "/"). Devolve para onde redirecionar."""
    state, code, error = params.get("state"), params.get("code"), params.get("error")
    if error:
        youtube_api.finish_auth_cancelled(state)
        msg = "Autorização cancelada" if error == "access_denied" else f"O Google recusou: {error}"
        return "/publicar?youtube=erro&msg=" + _q(msg)
    try:
        youtube_api.finish_auth(state, code or "")
    except YouTubeError as exc:
        return "/publicar?youtube=erro&msg=" + _q(str(exc))
    publisher.publisher.wake()
    return "/publicar?youtube=ok"


def _q(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:300])


# ------------------------------------------------------------------ fila
class PublishItem(BaseModel):
    clip_id: str
    title: str = Field(min_length=1, max_length=150)
    publish_at: float | None = None        # epoch (s); None = conforme a privacidade escolhida


class PublishIn(BaseModel):
    items: list[PublishItem] = Field(min_length=1, max_length=100)
    privacy: str = "private"               # private | unlisted | public (ignorado nos itens agendados)
    category_id: str | None = None
    notify: bool | None = None
    again: bool = False                    # permite enviar de novo um corte que já foi publicado


@router.post("/publish/youtube")
def publish_youtube(body: PublishIn):
    if body.privacy not in publisher.PRIVACIES:
        raise HTTPException(422, "Privacidade inválida")
    category = body.category_id or config.get("youtube.category_id")
    if category not in publisher.CATEGORIES:
        raise HTTPException(422, "Categoria inválida")
    notify = config.get("youtube.notify_subscribers") if body.notify is None else body.notify
    now = time.time()
    clips = []
    for it in body.items:
        clip = get_clip_or_404(it.clip_id)
        if clip["status"] != "done" or not clip.get("output_path"):
            raise HTTPException(409, "Este corte ainda não foi renderizado")
        if not publisher.clean_title(it.title):
            raise HTTPException(422, "Título vazio")
        if it.publish_at is not None and not now + publisher.MIN_SCHEDULE_S - 60 <= it.publish_at <= now + 180 * 86400:
            raise HTTPException(422, "Agende para pelo menos 15 minutos a partir de agora (até 6 meses)")
        if not body.again:
            prev = db.fetch_one("SELECT status FROM publications WHERE clip_id = ? AND platform = 'youtube' "
                                "AND status NOT IN ('failed','cancelled') LIMIT 1", (clip["id"],))
            if prev:
                title = (clip.get("titles") or [clip["id"]])[0]
                raise HTTPException(409, f"“{title[:60]}” já está na fila ou publicado. Marque \"enviar de novo\" "
                                         "se quiser mesmo duplicar.")
        clips.append((clip, it))
    created = [publisher.create(clip, title=it.title, privacy=body.privacy, publish_at=it.publish_at,
                                category_id=category, notify=bool(notify)) for clip, it in clips]
    return {"created": [publisher.public(p) for p in created], "connected": youtube_api.status()["connected"]}


@router.get("/publications")
def list_publications(clip_id: str | None = None, limit: int = 200):
    sql = ("SELECT p.*, c.thumb_path IS NOT NULL AS has_thumb, c.project_id FROM publications p "
           "JOIN clips c ON c.id = p.clip_id")
    params: tuple = ()
    if clip_id:
        sql += " WHERE p.clip_id = ?"
        params = (clip_id,)
    sql += (" ORDER BY CASE WHEN p.status IN ('uploading','queued','waiting_quota') THEN 0 ELSE 1 END, "
            "COALESCE(p.finished_at, p.created_at) DESC LIMIT ?")
    rows = db.fetch_all(sql, params + (max(1, min(limit, 500)),))
    return [publisher.public(r) for r in rows]


@router.post("/publications/{pub_id}/cancel")
def cancel_publication(pub_id: str):
    if not publisher.cancel(pub_id):
        raise HTTPException(409, "Este envio não está na fila")
    return {"ok": True}


@router.post("/publications/{pub_id}/retry")
def retry_publication(pub_id: str):
    if not publisher.retry(pub_id):
        raise HTTPException(409, "Só envios com falha ou cancelados podem ser tentados de novo")
    return {"ok": True}


@router.delete("/publications/{pub_id}")
def delete_publication(pub_id: str):
    pub = publisher.get(pub_id)
    if not pub:
        raise HTTPException(404, "Envio não encontrado")
    if pub["status"] in publisher.ACTIVE:
        raise HTTPException(409, "Cancele o envio antes de remover")
    db.execute("DELETE FROM publications WHERE id = ?", (pub_id,))   # só o registro; o vídeo no YouTube fica
    return {"ok": True}


@router.get("/clips/{cid}/tiktok-caption")
def clip_tiktok_caption(cid: str, title: int = 0):
    clip = get_clip_or_404(cid)
    titles = clip.get("titles") or []
    chosen = titles[title] if 0 <= title < len(titles) else None
    return {"caption": publisher.tiktok_caption(clip, chosen)}
