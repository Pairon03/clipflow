"""Títulos sobrepostos (tweet, caixa, citação), identidade do canal e endpoints de branding."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.api.common import validate_options
from app.main import create_app
from app.pipeline import branding, metadata, overlay

CARD = {"lead": "Craque Neto explica:", "quote": "Eu não gosto de jogar bola",
        "question": "Você jogaria de novo?", "guest": "Craque Neto",
        "headline": "Craque Neto explica: “Eu não gosto de jogar bola”"}


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def _put(client, values):
    r = client.put("/api/settings", json={"values": values})
    assert r.status_code == 200, r.text


def _png(color="red", size=(300, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_resolve_style_variar_rotates():
    assert [overlay.resolve_style("variar", "x", i) for i in range(4)] == ["tweet", "caixa", "citacao", "tweet"]
    assert overlay.resolve_style("caixa", "x", 5) == "caixa"
    assert overlay.resolve_style("??", "x") == "nenhum"
    assert overlay.resolve_style("variar", "abc") in overlay.ROTATION


def test_tweet_text_fixed_by_default_and_summary_mode(client):
    # padrão: frase fixa do canal, sem citar o convidado
    assert overlay.card_text("tweet", CARD) == "Você achou a melhor página de cortes do TikTok"
    _put(client, {"branding.tweet_mode": "resumo"})
    try:
        assert overlay.card_text("tweet", CARD) == CARD["headline"]
    finally:
        _put(client, {"branding.tweet_mode": "fixo"})
    assert overlay.card_text("caixa", CARD) == "Craque Neto responde:\nVocê jogaria de novo?"
    assert overlay.card_text("caixa", CARD | {"question": None}) == "Craque Neto explica:\nEu não gosto de jogar bola"
    assert overlay.card_text("citacao", CARD) == "Eu não gosto de jogar bola"
    assert overlay.card_text("nenhum", CARD) is None


def test_clean_text_removes_emoji_keeps_lines():
    assert overlay.clean_text("🔥 Olha  isso\n\n  agora 😱") == "Olha isso\nagora"


@pytest.mark.parametrize("style", ["tweet", "caixa", "citacao"])
def test_render_card_draws_white_card(style, tmp_path):
    out = overlay.render_card(style, CARD, tmp_path / f"{style}.png", 1080, 1920)
    img = Image.open(out)
    assert img.size == (1080, 1920) and img.mode == "RGBA"
    alpha = img.getchannel("A")
    assert alpha.getpixel((10, 1900)) == 0          # resto do quadro transparente
    bbox = alpha.getbbox()
    assert bbox[1] < 1920 * 0.25                     # título no topo
    assert overlay.render_card("nenhum", CARD, tmp_path / "n.png", 1080, 1920) is None
    if style != "tweet":  # o tweet usa a frase fixa do canal mesmo sem partes
        assert overlay.render_card(style, {}, tmp_path / "e.png", 1080, 1920) is None


@pytest.mark.parametrize("position,mid", [("center", 0.45), ("split", 0.5)])
def test_render_card_centered_positions(position, mid, tmp_path):
    for style in ("tweet", "caixa", "citacao"):
        out = overlay.render_card(style, CARD, tmp_path / f"{style}.png", 1080, 1920, position=position)
        top, bottom = Image.open(out).getchannel("A").getbbox()[1::2]
        assert abs((top + bottom) / 2 - 1920 * mid) <= 2      # centralizado na altura pedida
        assert bottom < 1920 * 0.7                             # acima da legenda (30% da base)


def test_long_text_is_limited_with_ellipsis():
    f = overlay._font("Poppins-Medium.ttf", 47)
    lines = overlay.wrap("palavra " * 80, f, 800, 4)
    assert len(lines) == 4 and lines[-1].endswith("…")
    assert all(f.getlength(line) <= 800 for line in lines)


def test_card_parts_use_real_speech():
    text = "Eu treinei todo dia durante dez anos. Você acha que vale a pena? Ninguém acreditava em mim."
    parts = metadata.card_parts(text, ["treinei"], "Craque Neto", "História", "treino")
    assert parts["guest"] == "Craque Neto" and parts["question"] == "Você acha que vale a pena?"
    assert parts["quote"] and parts["quote"] in text
    assert parts["topic_line"] == "Craque Neto sobre treino"
    assert parts["headline"].startswith(parts["lead"])


def test_validate_options_title_style():
    assert validate_options({})["title_style"] == "tweet"
    assert validate_options({"title_style": "variar"})["title_style"] == "variar"
    assert validate_options({"theme": False})["title_style"] == "nenhum"  # opção antiga
    assert validate_options({"title_duration": "inicio"})["title_duration"] == "inicio"
    with pytest.raises(Exception):
        validate_options({"title_style": "<script>"})


def test_branding_settings_and_avatar(client):
    _put(client, {"branding.channel_name": "Cortes do Pairon", "branding.channel_handle": "@cortes do pairon!"})
    b = client.get("/api/branding").json()
    assert b["name"] == "Cortes do Pairon" and b["handle"] == "@cortesdopairon" and not b["has_avatar"]
    assert b["tweet_text"] == "Você achou a melhor página de cortes do TikTok"

    assert client.put("/api/branding/avatar", content=b"nao e imagem").status_code == 422
    assert client.put("/api/branding/avatar", content=b"").status_code in (400, 413, 422)
    assert client.put("/api/branding/avatar", content=_png()).status_code == 200
    av = client.get("/api/branding/avatar")
    assert av.status_code == 200 and Image.open(io.BytesIO(av.content)).size == (256, 256)
    assert client.get("/api/branding").json()["has_avatar"]

    for style in ("tweet", "caixa", "citacao"):
        p = client.get(f"/api/branding/preview?style={style}")
        assert p.status_code == 200 and p.headers["content-type"].startswith("image/")

    assert client.delete("/api/branding/avatar").status_code == 200
    assert client.get("/api/branding/avatar").status_code == 404
    _put(client, {"branding.channel_name": "", "branding.channel_handle": ""})
    assert branding.current()["name"] == branding.DEFAULT_NAME


def test_branding_limits_rejected(client):
    r = client.put("/api/settings", json={"values": {"branding.tweet_mode": "outro"}})
    assert r.status_code == 422
    with pytest.raises(ValueError):
        config.coerce("branding.tweet_text", "x" * 500)
    with pytest.raises(ValueError):
        config.coerce("branding.channel_name", "x" * 41)


def test_captions_move_below_card_in_split(tmp_path):
    import pysubs2

    from app.pipeline import subtitles

    words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, t in enumerate("um dois três quatro cinco "
                                                                                       "seis sete oito nove dez".split())]
    st = subtitles.resolve_style("classic")
    path = subtitles.build_ass(words, st, 1080, 1920, tmp_path / "a.ass", centered=True, below=(2.0, 1100))
    subs = pysubs2.load(str(path))
    assert subs.styles["CaptionLow"].marginv == 1124
    assert {e.style for e in subs if e.start < 2000} == {"CaptionLow"}
    assert {e.style for e in subs if e.start >= 3000} == {"Caption"}


def test_color_filters_validated_and_in_filtergraph():
    from app.pipeline import color, render

    assert validate_options({})["color_filter"] == "nenhum"
    assert validate_options({"color_filter": "cinema"})["color_filter"] == "cinema"
    assert validate_options({})["title_position"] == "topo"
    assert validate_options({"title_position": "meio"})["title_position"] == "meio"
    for bad in ({"color_filter": "x;rm"}, {"title_position": "baixo"}):
        with pytest.raises(Exception):
            validate_options(bad)
    plan = {"layout": "center", "keyframes": [(0, 0.5)]}
    g = render.build_filtergraph([(0, 5)], plan, 1920, 1080, 30, None, 5, color_filter=color.chain("cinema"))
    assert f"[vgr]{color.chain('cinema')}[vlay]" in g
    assert "[vgr]" not in render.build_filtergraph([(0, 5)], plan, 1920, 1080, 30, None, 5)
    assert color.chain("nenhum") is None and color.chain("??") is None


def test_filter_preview_endpoint(client, tmp_path):
    assert client.get("/api/filters/preview?name=nao-existe").status_code == 422
    assert [f["key"] for f in client.get("/api/filters").json()][0] == "nenhum"
    assert client.get("/api/filters/preview?name=pb&project_id=../../x").status_code == 404


def test_band_title_and_text(tmp_path):
    card = {"headline": "Craque Neto mandou o papo reto", "topic_line": "Craque Neto sobre Neymar"}
    assert overlay.card_text("faixa", card) == "Craque Neto mandou o papo reto"
    assert overlay.card_text("faixa", {"topic_line": "Zico sobre Flamengo"}) == "Zico sobre Flamengo"
    out = overlay.render_card("faixa", card, tmp_path / "f.png", 1080, 1920, position="center")
    img = Image.open(out)
    band = overlay.band_height(1920)
    assert img.getpixel((5, 5)) == (255, 255, 255, 255)            # faixa branca sempre no topo
    assert img.getpixel((5, band + 5))[3] == 0                     # abaixo dela, transparente (vídeo)
    assert img.convert("L").crop((0, 0, 1080, band)).getextrema()[0] < 40  # texto preto na faixa


def test_yellow_caption_names_in_red_and_no_overlap(tmp_path):
    import pysubs2

    from app.pipeline import subtitles

    words = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.28} for i, t in
             enumerate("Você sabia que o Leo Dias falou com o Neto ontem à noite.".split())]
    st = subtitles.resolve_style("amarela")
    subs = pysubs2.load(str(subtitles.build_ass(words, st, 1080, 1920, tmp_path / "a.ass")))
    assert subs.styles["Caption"].italic and subs.styles["Caption"].fontsize == 116
    red = subtitles.ass_color("#FF2E2E")
    text = " ".join(e.text for e in subs)
    assert f"{{\\c{red}}}Leo" in text and f"{{\\c{red}}}Dias" in text and f"{{\\c{red}}}Neto" in text
    assert f"{{\\c{red}}}Você" not in text                          # início de frase não é nome
    events = sorted((e.start, e.end) for e in subs)
    assert len(events) >= 3
    for (_, e1), (s2, _) in zip(events, events[1:]):
        assert e1 <= s2                                             # nunca dois blocos ao mesmo tempo


def test_band_render_moves_video_below(sample_two, tmp_path):
    from app.pipeline import ffmpeg, render, transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 8.5)
    res = render.render_clip(src, info, {"id": "band00000001", "start": 0.45, "end": 8.5, "layout": "follow"}, words,
                             {"title_style_resolved": "faixa", "title_duration": "inicio",
                              "title_card": {"headline": "Teste da faixa"}, "caption_style": "amarela"},
                             tmp_path, tmp_path, tmp_path, null_context())
    assert res["render_info"]["title_style"] == "faixa"
    frame = tmp_path / "f.png"
    ffmpeg.run(["-ss", "6", "-i", res["output_path"], "-frames:v", "1", str(frame)])
    img = Image.open(frame).convert("RGB")
    assert img.size == (1080, 1920)
    assert min(img.getpixel((20, 20))) > 235                       # faixa continua depois de 4 s
    band = overlay.band_height(1920)
    assert max(img.getpixel((20, band + 40))) < 200                # vídeo começa logo abaixo
