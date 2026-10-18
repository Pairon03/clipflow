"""YouTube (yt-dlp simulado), Ollama (servidor HTTP falso), Whisper (se o modelo estiver disponível)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import config
from app.pipeline import llm, metadata, transcribe, youtube
from app.pipeline.context import null_context
from app.pipeline.errors import FatalPipelineError


# ------------------------------------------------------------- YouTube
@pytest.mark.parametrize("info,msg", [
    ({"availability": "private"}, "restrito"),
    ({"availability": "needs_auth"}, "restrito"),
    ({"is_live": True}, "ao vivo"),
    ({"live_status": "is_upcoming"}, "ao vivo"),
    ({"age_limit": 18}, "idade"),
    ({"has_drm": True}, "DRM"),
    ({"_type": "playlist"}, "playlist"),
    ({"duration": 10 ** 6}, "limite"),
])
def test_youtube_restricted_videos_rejected(info, msg):
    with pytest.raises(FatalPipelineError, match=msg):
        youtube.check_allowed(info)


def test_youtube_public_video_allowed():
    youtube.check_allowed({"availability": "public", "duration": 600, "age_limit": 0})


class FakeYDL:
    last_opts = None

    def __init__(self, opts):
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        if "private" in str(FakeYDL.last_opts.get("_mode", "")):
            raise Exception("ERROR: Private video. Sign in if you've been granted access")
        return {"title": "Episódio teste", "channel": "Canal", "duration": 1200, "availability": "public",
                "thumbnail": "https://i.ytimg.com/x.jpg", "license": "Creative Commons Attribution license"}


def test_youtube_metadata_uses_safe_options(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    meta = youtube.fetch_metadata("dQw4w9WgXcQ")
    assert meta["title"] == "Episódio teste" and meta["duration"] == 1200
    opts = FakeYDL.last_opts
    assert opts["noplaylist"] is True
    assert "cookiefile" not in opts and "cookiesfrombrowser" not in opts  # nunca usa credenciais


def test_youtube_private_error_message(monkeypatch):
    import yt_dlp

    class Private(FakeYDL):
        def extract_info(self, url, download=False):
            raise Exception("ERROR: Private video. Sign in if you've been granted access")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Private)
    with pytest.raises(FatalPipelineError, match="privado"):
        youtube.fetch_metadata("dQw4w9WgXcQ")


# ------------------------------------------------------------- Ollama
class OllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "Avalie os trechos" in req["prompt"]:
            resp = {"avaliacoes": [{"id": 0, "nota": 9, "motivo": "Faz sentido sozinho"},
                                   {"id": 1, "nota": 3, "motivo": "Depende do contexto"},
                                   {"id": 99, "nota": 10, "motivo": "id inválido"}]}
        else:
            resp = {"titulos": ["O método que mudou tudo", "“Frase que nunca foi dita”", "x" * 150],
                    "descricao": "Um trecho sobre repetição espaçada e constância nos estudos.",
                    "hashtags": ["#estudos", "aprendizado"], "palavras_chave": ["estudo"],
                    "texto_curto": "Repetição espaçada na prática."}
        body = json.dumps({"response": json.dumps(resp, ensure_ascii=False)}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_ollama():
    srv = HTTPServer(("127.0.0.1", 0), OllamaHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    config.set_override("ai.ollama_enabled", True)
    config.set_override("ai.ollama_url", f"http://127.0.0.1:{srv.server_port}")
    yield srv
    config.set_override("ai.ollama_enabled", False)
    srv.shutdown()


def test_ollama_status_and_rerank(fake_ollama):
    st = llm.status()
    assert st["reachable"] and st["model_installed"]
    res = llm.rerank([{"id": 0, "text": "a"}, {"id": 1, "text": "b"}])
    assert res == {0: {"nota": 9.0, "motivo": "Faz sentido sozinho"}, 1: {"nota": 3.0, "motivo": "Depende do contexto"}}


def test_ollama_metadata_is_validated(fake_ollama):
    text = "O método funciona assim: você revisa em intervalos cada vez maiores. Isso mudou tudo."
    m = metadata.generate(text, "Podcast X", "Educativo")
    assert m["engine"] == "ollama+heuristica"
    assert "O método que mudou tudo" in m["titles"]
    assert all("Frase que nunca foi dita" not in t for t in m["titles"])  # citação inventada descartada
    assert all(len(t) <= 100 for t in m["titles"])
    assert "#estudos" in m["hashtags"] and "#aprendizado" in m["hashtags"]


def test_ollama_unreachable_falls_back():
    config.set_override("ai.ollama_enabled", True)
    config.set_override("ai.ollama_url", "http://127.0.0.1:9")
    try:
        assert llm.rerank([{"id": 0, "text": "a"}]) is None
        m = metadata.generate("Você sabia que isso funciona? Funciona sim.", "", "Curiosidade")
        assert m["engine"] == "heuristica" and m["titles"]
    finally:
        config.set_override("ai.ollama_enabled", False)


def test_heuristic_titles_only_use_transcript_words():
    text = "Qual foi o maior erro no começo? O maior erro foi estudar tudo de uma vez."
    m = metadata.heuristic(text, "Podcast", "Pergunta e resposta")
    assert m["titles"][0] == "Qual foi o maior erro no começo?"
    for t in m["titles"]:
        for q in __import__("re").findall(r"“([^”]+)”", t):
            assert q.rstrip("…") in text


# ------------------------------------------------------------- Whisper
def test_whisper_transcription(sample_two, tmp_path):
    """Executa somente se o modelo Whisper já estiver em cache (o download exige acesso ao Hugging Face)."""
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        pytest.skip("faster-whisper não instalado")
    config.set_override("transcription.model", "tiny")
    try:
        if not transcribe.whisper_available()["model_cached"]:
            try:
                transcribe._load_model("tiny", "cpu", "int8")
            except Exception as exc:
                pytest.skip(f"Modelo Whisper indisponível neste ambiente: {exc}")
        wav = tmp_path / "a.wav"
        from app.pipeline import ffmpeg

        ffmpeg.extract_audio(sample_two["video"], wav)
        t = transcribe.transcribe_whisper(wav, sample_two["duration"], null_context())
        words = transcribe.all_words(t)
        assert len(words) > 50
        assert all(w["start"] <= w["end"] for w in words)
        text = " ".join(w["text"].lower() for w in words)
        assert "método" in text or "metodo" in text or "segredo" in text
    finally:
        config.set_override("transcription.model", "small")


def test_ytdlp_error_without_ansi_and_ffmpeg_hint():
    class E(Exception):
        pass

    msg = youtube._friendly(E("\x1b[0;31mERROR:\x1b[0m You have requested merging of multiple formats but "
                              "ffmpeg is not installed. Aborting due to --abort-on-error"))
    assert "\x1b" not in msg and "winget install Gyan.FFmpeg" in msg
    assert youtube._friendly(E("\x1b[0;31mERROR:\x1b[0m Video unavailable")) == "Vídeo indisponível."


def test_missing_ffmpeg_fails_fast_with_instructions(monkeypatch):
    from app.pipeline import ffmpeg, runner
    from app.pipeline.context import null_context

    monkeypatch.setattr(ffmpeg, "_find", lambda name: None)
    with pytest.raises(FatalPipelineError, match="winget install Gyan.FFmpeg"):
        runner.run_analysis("000000000000", null_context())


def test_whisper_receives_decoded_audio(sample_two, tmp_path, monkeypatch):
    """O Whisper recebe o áudio já decodificado (numpy), sem depender do decodificador PyAV."""
    import numpy as np
    from types import SimpleNamespace

    from app.pipeline import ffmpeg

    wav = tmp_path / "a.wav"
    ffmpeg.extract_audio(sample_two["video"], wav)
    seen = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            seen["kw"] = kw
            w = [SimpleNamespace(word=" Olá", start=1.0, end=1.4, probability=0.9),
                 SimpleNamespace(word=" mundo.", start=1.5, end=2.0, probability=0.8)]
            seg = SimpleNamespace(start=1.0, end=2.0, text=" Olá mundo.", words=w, no_speech_prob=0.0, avg_logprob=-0.2)
            return iter([seg]), SimpleNamespace(language="pt", duration=len(audio) / 16000)

    monkeypatch.setattr(transcribe, "_load_model", lambda *a: FakeModel())
    t = transcribe.transcribe_whisper(wav, sample_two["duration"], null_context())
    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert abs(len(audio) / 16000 - sample_two["duration"]) < 0.2
    assert -1.0 <= audio.min() and audio.max() <= 1.0 and np.abs(audio).max() > 0.05  # há fala
    assert seen["kw"]["word_timestamps"] is True
    assert [w["text"] for w in transcribe.all_words(t)] == ["Olá", "mundo."]
