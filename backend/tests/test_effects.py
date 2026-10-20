"""Efeitos de edição: censura de palavrões, efeitos sonoros, zooms e transição depois do gancho."""
import wave
from pathlib import Path

import numpy as np
import pytest

from app import config, db
from app.api.common import validate_options
from app.pipeline import censor, ffmpeg, render, sfx


def test_profanity_detection_and_mask():
    for word in ("porra,", "Caralho!", "foda-se", "fodase", "PQP", "merdinha", "cu", "arrombado"):
        assert censor.is_profane(word), word
    for word in ("porrada", "viaduto", "computador", "putz", "curioso", "pau", "cuidado", "fodder"):
        assert not censor.is_profane(word), word
    assert censor.mask("porra,") == "p****,"
    assert censor.censor_text("Que porra é essa, caralho!") == "Que p**** é essa, c******!"


def test_censor_words_merges_spans_and_extra_words():
    words = [{"text": "que", "start": 0.0, "end": 0.2}, {"text": "porra", "start": 0.3, "end": 0.6},
             {"text": "caralho", "start": 0.62, "end": 0.9}, {"text": "beleza", "start": 1.5, "end": 1.9}]
    out, spans = censor.censor_words(words)
    assert [w["text"] for w in out] == ["que", "p****", "c******", "beleza"]
    assert spans == [(0.25, 0.95)]                       # palavras vizinhas viram um intervalo só
    db.save_setting("censor.extra_words", "beleza, Treta")
    try:
        assert censor.censor_words(words)[0][3]["text"] == "b*****"
        assert censor.is_profane("treta")
    finally:
        db.save_setting("censor.extra_words", "")
    assert censor.mute_filter([]) is None
    assert "between(t,0.250,0.950)" in censor.mute_filter(spans)


def test_censor_meta_masks_titles_and_card():
    meta = {"titles": ["Ele disse porra nenhuma"], "description": "🔥 Caralho!", "short_text": "ok",
            "card": {"quote": "Que merda", "guest": "Fulano"}}
    out = censor.censor_meta(meta)
    assert out["titles"] == ["Ele disse p**** nenhuma"] and out["description"] == "🔥 C******!"
    assert out["card"] == {"quote": "Que m****", "guest": "Fulano"}


def test_sfx_track(tmp_path):
    assert sfx.build_track(5, tmp_path / "a.wav", "nenhum", whoosh_at=2.0) is None
    p = sfx.build_track(5, tmp_path / "a.wav", "sutil", whoosh_at=2.0, pop_at=[0.05])
    with wave.open(str(p)) as wf:
        assert wf.getframerate() == sfx.SR and wf.getnframes() == int(5.5 * sfx.SR)
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16) / 32768
    peak_at = np.argmax(np.abs(x[int(1.0 * sfx.SR):int(3.0 * sfx.SR)])) / sfx.SR + 1.0
    assert abs(peak_at - 2.0) < 0.1                      # pico do whoosh na transição
    assert np.abs(x).max() <= sfx.LEVELS["sutil"] + 0.01  # discreto
    assert sfx.build_track(5, tmp_path / "b.wav", None, bips=[(1.0, 1.3)]) is not None  # bipe sem efeitos


def test_effects_filter_and_audio_graph():
    assert render.effects_filter([], "nenhuma", 3.0, 1080, 1920) is None
    fx = render.effects_filter([(5.0, 6.0)], "zoom", 3.0, 1080, 1920)
    assert "eval=frame" in fx and "crop=1080:1920" in fx and "gte(t,3.000)" in fx
    assert "eq=brightness" in render.effects_filter([], "flash", 3.0, 1080, 1920)
    plan = {"layout": "center", "keyframes": [(0, 0.5)]}
    g = render.build_filtergraph([(0, 5)], plan, 1920, 1080, 30, None, 5, video_fx=fx,
                                 mute=censor.mute_filter([(1.0, 1.4)]), sfx_input=1)
    assert f"[vgr]{fx}[vlay]" in g and "amix=inputs=2:normalize=0" in g and "[1:a]" in g
    assert "volume=volume='if(between(t,1.000,1.400),0,1)'" in g


def test_validate_effect_options():
    o = validate_options({})
    assert (o["transition"], o["zoom_fx"], o["sfx"], o["censor"]) == ("zoom", True, "sutil", "mudo")
    for bad in ({"transition": "explodir"}, {"sfx": "alto"}, {"censor": "x"}):
        with pytest.raises(Exception):
            validate_options(bad)


def _audio(path, tmp_path):
    path = Path(path)
    wav = tmp_path / f"{path.stem}.wav"
    ffmpeg.run(["-i", str(path), "-ac", "1", "-ar", "16000", str(wav)])
    with wave.open(str(wav)) as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def test_render_with_effects_mutes_profanity(sample_two, tmp_path):
    from app.pipeline import transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    words[30]["text"] = "porra"
    base = {"pace": "tiktok", "cold_open": True, "transition": "zoom", "zoom_fx": True, "censor": "mudo"}
    clip = {"start": 0.45, "end": 30.5, "layout": "follow"}
    res = render.render_clip(src, info, clip | {"id": "fx0000000001"}, [dict(w) for w in words],
                             base | {"sfx": "sutil"}, tmp_path, tmp_path, tmp_path, null_context())
    quiet = render.render_clip(src, info, clip | {"id": "fx0000000002"}, [dict(w) for w in words],
                               base | {"sfx": "nenhum"}, tmp_path, tmp_path, tmp_path, null_context())
    ri = res["render_info"]
    assert ri["transition"] == "zoom" and ri["zooms"] >= 1 and ri["sfx"] == "sutil" and ri["muted_words"] >= 1
    assert not list(tmp_path.glob("*.sfx.wav"))          # faixa temporária apagada
    assert res["duration"] == pytest.approx(quiet["duration"], abs=0.05)
    x, q = _audio(res["output_path"], tmp_path), _audio(quiet["output_path"], tmp_path)

    def rms(a, s, e):
        seg = a[int(s * 16000):int(e * 16000)]
        return float(np.sqrt(np.mean(seg ** 2)))

    masked = [w for w in res["words_out"] if w["text"].startswith("p*")]
    assert masked and all("porra" not in w["text"] for w in res["words_out"])
    for w in masked:
        assert rms(x, w["start"] + 0.06, w["end"] - 0.06) < 0.003      # palavrão silenciado
    T = ri["cold_open"][1] - ri["cold_open"][0]
    diff = x[:len(q)] - q[:len(x)]
    assert rms(diff, T - 0.3, T + 0.1) > 0.01                          # whoosh na transição
    calm = [(a, a + 1.5) for a in np.arange(T + 1, res["duration"] - 2, 0.5)
            if all(not (a - 0.2 <= z <= a + 1.7) for z in ri["zoom_times"])]
    assert calm and rms(diff, *calm[0]) < 0.003          # fora dos efeitos a fala fica idêntica
    srt = (tmp_path / "fx0000000001.srt").read_text(encoding="utf-8")
    assert "porra" not in srt and "p****" in srt


def test_concat_clean_variant_skips_ffmpeg_zoom():
    import inspect

    from app.pipeline import runner

    assert inspect.getsource(runner).count('"zoom_fx": False') == 2
    assert config.get("censor.extra_words") == ""


def test_pick_flip_once_away_from_hook_and_zooms():
    from app.pipeline import enhance

    words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.35}
             for i, t in enumerate(("Eu nunca vou esquecer aquele dia incrível! " * 12).split())]
    dur = words[-1]["end"] + 0.5
    zooms = [(dur * 0.5, dur * 0.5 + 1.5)]
    a, b = enhance.pick_flip(words, dur, avoid=[(0.0, 5.0)] + zooms)
    assert b - a == pytest.approx(enhance.FLIP_S, abs=0.01)
    assert 0.3 * dur <= a <= 0.8 * dur
    for za, zb in zooms:
        assert a >= zb + enhance.FLIP_MARGIN_S or b <= za - enhance.FLIP_MARGIN_S
    assert enhance.pick_flip(words[:10], 8.0) is None              # vídeo curto: sem inversão
    fx = render.effects_filter([], None, None, 1080, 1920, flip=(a, b))
    assert fx == f"hflip=enable='between(t,{a:.3f},{b:.3f})'"
    assert validate_options({})["flip_fx"] is True


def test_flip_render_mirrors_only_during_window(sample_moving, tmp_path):
    """O quadro dentro da janela é o espelho do original; fora dela, volta ao normal."""
    from PIL import Image, ImageChops

    from app.pipeline import transcribe
    from app.pipeline.context import null_context

    src = sample_moving["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_moving["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    clip = {"start": 0.45, "end": 30.5, "layout": "follow"}
    flip = render.render_clip(src, info, clip | {"id": "flip00000001"}, words, {"flip_fx": True, "captions": False},
                              tmp_path, tmp_path, tmp_path, null_context())
    plain = render.render_clip(src, info, clip | {"id": "flip00000002"}, words, {"captions": False},
                               tmp_path, tmp_path, tmp_path, null_context())
    a, b = flip["render_info"]["flip"]
    assert plain["render_info"]["flip"] is None

    def frame(path, at, name):
        out = tmp_path / name
        ffmpeg.run(["-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=270:480", str(out)])
        return Image.open(out).convert("L")

    def diff(x, y):
        return sum(ImageChops.difference(x, y).getdata()) / (x.width * x.height)

    mid = (a + b) / 2
    f_in, p_in = frame(flip["output_path"], mid, "fi.png"), frame(plain["output_path"], mid, "pi.png")
    assert diff(f_in, p_in.transpose(Image.FLIP_LEFT_RIGHT)) < diff(f_in, p_in)   # dentro: espelhado
    f_out, p_out = frame(flip["output_path"], b + 1.0, "fo.png"), frame(plain["output_path"], b + 1.0, "po.png")
    assert diff(f_out, p_out) < 3                                                    # depois: normal de novo


def test_preferences_api_roundtrip():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(start_worker=False)) as client:
        client.delete("/api/preferences")
        assert client.get("/api/preferences").json() == {"options": {}, "saved": False}
        r = client.put("/api/preferences", json={"options": {"title_style": "faixa", "flip_fx": False,
                                                             "caption_style": "amarela", "count": 3}})
        assert r.status_code == 200
        got = client.get("/api/preferences").json()
        assert got["saved"] and got["options"]["title_style"] == "faixa" and got["options"]["flip_fx"] is False
        assert got["options"]["count"] == 3 and "review" not in got["options"]     # só escolhas de edição
        assert client.put("/api/preferences", json={"options": {"title_style": "<x>"}}).status_code == 422
        client.delete("/api/preferences")
        assert client.get("/api/preferences").json()["saved"] is False
