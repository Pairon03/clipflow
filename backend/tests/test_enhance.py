"""Decisões automáticas de edição: zoom de ênfase e texto de gancho."""
import pytest

from app.pipeline import enhance
from app.pipeline.transcribe import _split_words


def words_for(sentences, start=0.5, wps=3.0, gap=0.4):
    out, t = [], start
    for s in sentences:
        d = len(s.split()) / wps
        out += _split_words(s, t, t + d)
        t += d + gap
    return out, t


TEXT = [
    "Hoje eu quero falar sobre estudos.",
    "Isso mudou minha vida completamente!",
    "A gente começou devagar com a rotina.",
    "Você sabia que noventa por cento das pessoas desistem?",
    "Depois veio a parte mais tranquila do processo.",
    "Nunca desista do seu sonho, de verdade.",
]


def test_zooms_land_on_emphasis_and_respect_spacing():
    words, dur = words_for(TEXT)
    zooms = enhance.pick_zooms(words, dur)
    assert 1 <= len(zooms) <= max(1, int(dur // enhance.SECONDS_PER_ZOOM))
    for a, b in zip(zooms, zooms[1:]):
        assert b[0] - a[1] >= enhance.MIN_GAP_S
    assert all(s >= enhance.HOOK_DURATION_S for s, _ in zooms)  # não briga com o gancho
    texts = [" ".join(w["text"] for w in words if s - 0.01 <= w["start"] < e) for s, e in zooms]
    assert any("mudou" in t or "Nunca" in t or "noventa" in t or "sabia" in t for t in texts), texts


def test_no_zoom_without_emphasis():
    words, dur = words_for(["a casa é azul.", "o carro é verde.", "a mesa é bege."] * 3)
    assert enhance.pick_zooms(words, dur) == []


def test_zoom_keyframes_shape():
    keys = enhance.zoom_keyframes([(4.0, 5.0)], 20.0)
    assert [k["value"] for k in keys] == [1.0, enhance.ZOOM_SCALE, enhance.ZOOM_SCALE, 1.0]
    ats = [k["at"] for k in keys]
    assert ats == sorted(ats) and all(0 <= a <= 1 for a in ats)
    assert ats[1] == pytest.approx((4.0 + enhance.ZOOM_IN_S) / 20.0, abs=1e-4)
    assert enhance.zoom_keyframes([], 10) == []


def test_hook_text():
    h = enhance.hook_text(["“O maior erro foi estudar tudo de uma vez”", "outro"])
    assert "“" not in h and h.count("\n") <= 2
    assert all(len(line) <= 22 for line in h.split("\n"))
    assert enhance.hook_text(["x" * 200, "Título curto e bom"]) == "Título curto e bom"
    assert enhance.hook_text([]) is None


def test_cold_open_picks_emphatic_sentence_later_in_clip():
    words, dur = words_for(TEXT)
    hook = enhance.pick_cold_open(words, 0.0, dur)
    assert hook is not None
    a, b = hook
    assert a >= enhance.COLD_OPEN_MIN_POS_S - 0.1
    assert enhance.COLD_OPEN_MIN_S - 0.1 <= b - a <= enhance.COLD_OPEN_MAX_S + 0.3
    spoken = " ".join(w["text"] for w in words if a - 0.01 <= w["start"] and w["end"] <= b + 0.01)
    assert any(k in spoken for k in ("mudou", "Nunca", "noventa", "sabia")), spoken


def test_no_cold_open_for_short_or_flat_clips():
    words, dur = words_for(["a casa é azul.", "o carro é verde.", "a mesa é bege."] * 3)
    assert enhance.pick_cold_open(words, 0.0, dur) is None
    short, d2 = words_for(TEXT[:1])
    assert enhance.pick_cold_open(short, 0.0, d2) is None


def test_theme_text_short_and_wrapped():
    t = enhance.theme_text(["Qual foi o maior erro que você cometeu no começo da carreira?"])
    assert len(t.replace("\n", " ")) <= 44 and t.count("\n") <= 2
    assert enhance.theme_text([]) is None


def test_description_is_catchy_not_transcript():
    from app.pipeline import metadata

    text = ("Qual foi o maior erro da sua carreira? O maior erro foi brigar com o treinador. "
            "Eu nunca mais faço isso!")
    m = metadata.heuristic(text, "CRAQUE NETO - Podpah #1093", "Pergunta e resposta")
    d = m["description"]
    assert not d.startswith(text[:40])  # não começa com a transcrição
    first = d.split("\n")[0]
    assert any(ord(ch) > 0x2000 for ch in first)  # gancho com emoji
    lines = d.split("\n\n")
    assert lines[-3].endswith(("👇", "📌", "🔥", "❤️", "👀"))  # chamada antes do crédito e das hashtags
    assert d.startswith("🎯 No Podpah, Craque Neto responde: “Qual foi o maior erro da sua carreira?”")
    assert "#craqueneto" in m["hashtags"] and "#podpah" in m["hashtags"] and "#cortes" in m["hashtags"]
    assert m["titles"][1].startswith("Craque Neto: “")
    assert metadata.parse_source("CRAQUE NETO - Podpah #1093") == ("Craque Neto", "Podpah")
    assert metadata.parse_source("Um vídeo qualquer") == (None, None)
