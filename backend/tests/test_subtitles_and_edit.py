import pysubs2
import pytest

from app.pipeline import editing, subtitles, transcribe
from app.pipeline.transcribe import _split_words


def words_of(text, start=0.0, end=None):
    end = end if end is not None else start + len(text.split()) * 0.35
    return _split_words(text, start, end)


def test_grouping_limits():
    w = words_of("Esta é uma frase bastante longa para testar a quebra inteligente das legendas. E outra frase curta.")
    groups = subtitles.group_words(w, max_chars=22, max_words=4)
    for g in groups:
        assert len(g) <= 5  # pode juntar uma palavra "pendurada"
        assert sum(len(x["text"]) + 1 for x in g) - 1 <= 22 + 5
    # pontuação final fecha bloco
    ends = [g[-1]["text"] for g in groups]
    assert "legendas." in ends


def test_pause_breaks_group():
    w = words_of("um dois", 0, 1) + words_of("três quatro", 3, 4)
    groups = subtitles.group_words(w, 40, 10)
    assert len(groups) == 2


@pytest.mark.parametrize("style", ["classic", "neon", "minimal", "impact"])
def test_ass_has_word_highlight_and_sync(tmp_path, style):
    w = words_of("Você sabia que o segredo é a constância?", 1.0, 4.0)
    st = subtitles.resolve_style(style)
    path = subtitles.build_ass(w, st, 1080, 1920, tmp_path / "x.ass")
    subs = pysubs2.load(str(path))
    assert subs.info["PlayResX"] == "1080"
    events = [e for e in subs if not e.is_comment]
    assert len(events) == len(w)  # um evento por palavra falada
    for ev, word in zip(events, w):
        assert abs(ev.start / 1000 - word["start"]) <= 0.011  # ASS tem resolução de centésimos
        assert ev.end > ev.start
    if st.highlight_active:
        assert subtitles.ass_color(st.highlight) in events[0].text
    if style == "impact":
        assert "VOCÊ" in events[0].text  # caixa alta
    style_obj = subs.styles["Caption"]
    assert style_obj.marginv == int(1920 * st.position)


def test_custom_colors_validated():
    st = subtitles.resolve_style("classic", {"highlight": "#00FF00", "size": 999})
    assert st.highlight == "#00FF00" and st.size == 160
    with pytest.raises(ValueError):
        subtitles.resolve_style("classic", {"highlight": "vermelho"})


def test_filter_path_escaping():
    assert subtitles.ffmpeg_filter_path(__import__("pathlib").PureWindowsPath("C:/dados/a.ass")) == r"C\:/dados/a.ass"


def test_realign_keeps_timing():
    w = words_of("eu acho que a gente precisa estudar mais", 10, 14)
    out = editing.realign(w, "Eu acho que a gente precisa estudar MAIS.")
    assert [x["text"] for x in out][-1] == "MAIS."
    assert [x["start"] for x in out] == [x["start"] for x in w]


def test_realign_replace_and_insert():
    w = words_of("o clip flow e muito bom", 0, 3)
    out = editing.realign(w, "o ClipFlow é muito, muito bom")
    texts = [x["text"] for x in out]
    assert texts == ["o", "ClipFlow", "é", "muito,", "muito", "bom"]
    assert all(out[i]["start"] <= out[i + 1]["start"] for i in range(len(out) - 1))
    assert out[0]["start"] == 0 and abs(out[-1]["end"] - w[-1]["end"]) < 0.5
    with pytest.raises(ValueError):
        editing.realign(w, "   ")


def test_srt_import(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\n<i>Olá</i> mundo bonito\n\n2\n00:00:04,000 --> 00:00:05,000\nTchau.\n",
                   encoding="utf-8")
    t = transcribe.import_subtitles(srt, 10)
    assert t["engine"] == "subtitle-import"
    words = transcribe.all_words(t)
    assert [w["text"] for w in words] == ["Olá", "mundo", "bonito", "Tchau."]
    assert words[0]["start"] == 1.0 and words[2]["end"] == 3.0
    assert all(w["start"] < w["end"] for w in words)
    out = transcribe.to_srt(t["segments"], tmp_path / "o.srt")
    assert "Olá mundo bonito" in out.read_text(encoding="utf-8")
