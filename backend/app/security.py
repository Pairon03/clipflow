"""Validações de entrada: URLs, arquivos enviados e declaração de direitos."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

ALLOWED_VIDEO_EXT = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".mts", ".m2ts",
    ".flv", ".wmv", ".3gp",
}
ALLOWED_SUB_EXT = {".srt", ".vtt"}

RIGHTS_BASES = {
    "own": "Conteúdo próprio",
    "licensed": "Licença ou autorização do titular",
    "creative_commons": "Licença Creative Commons que permite reutilização",
    "other": "Outra base legal (descreva)",
}


class ValidationError(ValueError):
    pass


def parse_youtube_url(url: str) -> str:
    """Retorna o ID do vídeo ou lança ValidationError.

    Aceita apenas vídeos individuais (watch, youtu.be, shorts, live, embed).
    Playlists e canais são recusados.
    """
    if not isinstance(url, str) or len(url) > 500:
        raise ValidationError("URL inválida")
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValidationError("URL inválida") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("Apenas links http(s) são aceitos")
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise ValidationError("O link precisa ser do YouTube (youtube.com ou youtu.be)")
    if parsed.username or parsed.password or (parsed.port not in (None, 80, 443)):
        raise ValidationError("URL inválida")

    vid = None
    path = parsed.path.rstrip("/")
    if host == "youtu.be":
        vid = path.lstrip("/").split("/")[0]
    elif path == "/watch":
        vid = (parse_qs(parsed.query).get("v") or [None])[0]
    else:
        m = re.match(r"^/(shorts|live|embed|v)/([^/]+)$", path)
        if m:
            vid = m.group(2)
    if not vid or not VIDEO_ID_RE.match(vid):
        raise ValidationError("Não foi possível identificar o vídeo. Use um link de vídeo individual.")
    return vid


def canonical_youtube_url(video_id: str) -> str:
    if not VIDEO_ID_RE.match(video_id):
        raise ValidationError("ID de vídeo inválido")
    return f"https://www.youtube.com/watch?v={video_id}"


def check_video_filename(filename: str | None) -> str:
    """Valida a extensão e devolve-a (minúscula). O nome original nunca vira caminho em disco."""
    if not filename:
        raise ValidationError("Arquivo sem nome")
    name = filename.replace("\\", "/").split("/")[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in ALLOWED_VIDEO_EXT:
        raise ValidationError(
            f"Formato não suportado ({ext or 'sem extensão'}). Use: "
            + ", ".join(sorted(e.lstrip('.') for e in ALLOWED_VIDEO_EXT))
        )
    return ext


def check_subtitle_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in ALLOWED_SUB_EXT:
        raise ValidationError("Legenda deve ser .srt ou .vtt")
    return ext


def display_name(filename: str | None, fallback: str = "Vídeo") -> str:
    """Nome amigável para exibir (sem caminho, sem caracteres de controle)."""
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return (name or fallback)[:120]


def check_rights(confirmed: bool, basis: str, note: str) -> tuple[str, str]:
    if not confirmed:
        raise ValidationError("É preciso confirmar que você tem direito de uso do conteúdo.")
    if basis not in RIGHTS_BASES:
        raise ValidationError("Selecione a base legal de uso do conteúdo.")
    note = (note or "").strip()
    if basis in {"licensed", "other", "creative_commons"} and len(note) < 5:
        raise ValidationError("Descreva a autorização/licença (ex.: contrato, e-mail, link da licença).")
    return basis, note[:2000]


def safe_filename(text: str, max_len: int = 60) -> str:
    """Gera um nome de arquivo seguro para downloads (ex.: nome do ZIP)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", t).strip("._")
    return (t or "arquivo")[:max_len]
