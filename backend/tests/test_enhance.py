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
