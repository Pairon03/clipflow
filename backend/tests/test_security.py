import pytest

from app import storage
from app.security import (ValidationError, check_rights, check_subtitle_filename, check_video_filename,
                          parse_youtube_url, safe_filename)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "http://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "www.youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_valid_youtube_urls(url):
    assert parse_youtube_url(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    "",
    "https://vimeo.com/123456",
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/@canal",
    "https://www.youtube.com/watch?v=curto",
    "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
    "https://user:pass@www.youtube.com/watch?v=dQw4w9WgXcQ",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ;rm -rf /",
    "https://www.youtube.com/watch?v=" + "a" * 600,
])
def test_invalid_youtube_urls(url):
    with pytest.raises(ValidationError):
        parse_youtube_url(url)


def test_video_filename_validation():
    assert check_video_filename("Episódio 1.MP4") == ".mp4"
    assert check_video_filename("C:\\Users\\x\\video.mov") == ".mov"
    for bad in ["script.exe", "video", "../../etc/passwd", "a.mp4.bat", None]:
        with pytest.raises(ValidationError):
            check_video_filename(bad)
    assert check_subtitle_filename("legenda.srt") == ".srt"
    with pytest.raises(ValidationError):
        check_subtitle_filename("legenda.txt")


def test_rights_required():
    with pytest.raises(ValidationError):
        check_rights(False, "own", "")
    with pytest.raises(ValidationError):
        check_rights(True, "invalido", "")
    with pytest.raises(ValidationError):
        check_rights(True, "licensed", "")  # licença exige documentação
    assert check_rights(True, "own", "") == ("own", "")
    assert check_rights(True, "licensed", "Contrato assinado em 10/2026")[0] == "licensed"


def test_path_sanitization(tmp_path):
    assert storage.safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()
    with pytest.raises(storage.UnsafePathError):
        storage.safe_join(tmp_path, "..", "fora.txt")
    with pytest.raises(storage.UnsafePathError):
        storage.check_id("../../etc")
    with pytest.raises(storage.UnsafePathError):
        storage.ensure_inside_root("/etc/passwd")
    assert storage.check_id("0123456789ab") == "0123456789ab"


def test_safe_filename():
    assert safe_filename("Título: “ótimo” / teste?") == "Titulo_otimo_teste"
    assert safe_filename("../../") == "arquivo"


def test_update_check_detects_changed_frontend(tmp_path):
    from app import update_check as u

    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "App.vue").write_text("v1")
    (fe / "package.json").write_text("{}")
    assert u.frontend_outdated(fe)                 # nunca compilado
    (fe / "dist").mkdir()
    (fe / "dist" / "index.html").write_text("<html>")
    assert u.frontend_outdated(fe)                 # compilado sem marca (versão antiga do setup)
    u.mark_frontend_built(fe)
    assert not u.frontend_outdated(fe)
    (fe / "src" / "App.vue").write_text("v2")      # atualização copiada por cima
    assert u.frontend_outdated(fe)
    u.mark_frontend_built(fe)
    (fe / "src" / "Novo.vue").write_text("x")      # arquivo novo
    assert u.frontend_outdated(fe)
