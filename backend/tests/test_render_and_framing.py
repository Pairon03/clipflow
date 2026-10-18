import re

import pytest

from app import config
from app.pipeline import ffmpeg, framing, render


def eval_ffmpeg_expr(expr: str, t: float) -> float:
    """Avalia a expressão de crop do FFmpeg em Python (if/lt) para conferir a interpolação."""
    py = expr.replace("if(", "_if(").replace("lt(", "_lt(")
    return eval(py, {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b, "t": t})


def test_timemap_and_keep_intervals():
    words = [{"text": "a", "start": 10.0, "end": 10.5}, {"text": "b", "start": 10.6, "end": 11.0},
             {"text": "c", "start": 13.0, "end": 13.4}, {"text": "d", "start": 13.5, "end": 14.0}]
    iv = render.keep_intervals(words, 10.0, 14.2, trim=True, max_pause=0.7)
    assert len(iv) == 2  # pausa de 2s removida
    tm = render.TimeMap(iv)
    assert tm.duration == pytest.approx(4.2 - (iv[1][0] - iv[0][1]))
    assert tm.map(0.5) == pytest.approx(0.5)
    assert tm.map(3.0) == pytest.approx(iv[0][1] - iv[0][0] + 3.0 - iv[1][0])
    assert tm.map(2.0) == pytest.approx(iv[0][1])  # dentro da pausa: encosta no próximo trecho
    assert render.keep_intervals(words, 10, 14.2, trim=False) == [(0.0, pytest.approx(4.2))]


def test_crop_expression_interpolates_and_clamps():
    kf = [(0.0, 0.3), (2.0, 0.5), (4.0, 0.9)]
    expr = render.crop_x_expr(kf, 1920, 608)
    assert eval_ffmpeg_expr(expr, 0) == pytest.approx(0.3 * 1920 - 304)
    assert eval_ffmpeg_expr(expr, 1.0) == pytest.approx(((0.3 + 0.5) / 2) * 1920 - 304, abs=0.2)
    assert eval_ffmpeg_expr(expr, 10.0) == pytest.approx(1920 - 608)  # limitado à borda
    assert float(render.crop_x_expr([(0, 0.5)], 1920, 608)) == 656.0


def test_rdp_reduces_keyframes():
    pts = [(i / 10, 0.5 + 0.001 * (i % 2)) for i in range(200)]
    assert len(framing.rdp(pts, 0.004)) == 2


def test_smooth_path_moves_without_jitter():
    times = [i / 6 for i in range(60)]
    targets = [0.3 if t < 5 else 0.7 for t in times]
    path = framing.smooth_path(times, targets, 0.316, 6)
    xs = [x for _, x in path]
    assert xs[0] == pytest.approx(0.3, abs=0.01)
    assert xs[-1] == pytest.approx(0.7, abs=0.03)
    assert max(abs(b - a) for a, b in zip(xs, xs[1:])) < 0.316 * 0.9 / 6 + 1e-6  # limite de velocidade
    # pequenas oscilações dentro da zona morta não movem a câmera
    jitter = framing.smooth_path(times, [0.5 + (0.01 if i % 2 else -0.01) for i in range(60)], 0.316, 6)
    assert max(x for _, x in jitter) - min(x for _, x in jitter) < 0.005


def test_face_detector_loads():
    det = framing.get_detector()
    assert det.available, "Nenhum detector de rosto disponível"


def test_framing_follow_moving_face(sample_moving):
    info = ffmpeg.probe(sample_moving["video"])
    plan = framing.analyze(sample_moving["video"], 5, 35, info.width, info.height, layout="auto")
    assert plan["layout"] == "follow"
    assert plan["faces"] >= 1
    xs = [x for _, x in plan["keyframes"]]
    assert xs[-1] > xs[0] + 0.15  # câmera acompanhou o rosto para a direita
    face_x_at_end = 0.25 + 0.5 * (35 / sample_moving["duration"])
    assert abs(xs[-1] - face_x_at_end) < plan["crop_w"] / 2  # rosto dentro do recorte


def test_framing_two_faces_split(sample_two):
    info = ffmpeg.probe(sample_two["video"])
    plan = framing.analyze(sample_two["video"], 0, 20, info.width, info.height, layout="auto")
    assert plan["layout"] == "split"
    assert len(plan["panels"]) == 2
    assert plan["panels"][0]["cx"] < 0.4 < 0.6 < plan["panels"][1]["cx"]


def test_framing_no_faces_falls_back_to_center(sample_none):
    info = ffmpeg.probe(sample_none["video"])
    plan = framing.analyze(sample_none["video"], 0, 10, info.width, info.height, layout="auto")
    assert plan["layout"] == "center" and plan["keyframes"] == [(0.0, 0.5)]


def test_framing_manual_and_disabled(sample_two, monkeypatch):
    info = ffmpeg.probe(sample_two["video"])
    plan = framing.analyze(sample_two["video"], 0, 10, info.width, info.height, layout="manual", manual_x=0.0)
    assert plan["keyframes"][0][1] == pytest.approx(plan["crop_w"] / 2)  # limitado à borda esquerda
    config.set_override("render.face_tracking", False)
    try:
        plan = framing.analyze(sample_two["video"], 0, 10, info.width, info.height, layout="auto")
        assert plan["layout"] == "center"
    finally:
        config.set_override("render.face_tracking", True)


@pytest.mark.parametrize("layout", ["follow", "split", "fit", "speaker"])
def test_render_each_layout(sample_two, tmp_path, layout):
    """Renderiza um corte curto em cada layout e confere o MP4 final (H.264/AAC 1080x1920)."""
    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    words = [{"text": t, "start": 1.0 + i * 0.4, "end": 1.35 + i * 0.4} for i, t in enumerate("um teste de render".split())]
    clip = {"id": f"{layout[:4]:0<12}"[:12], "start": 0.5, "end": 6.5, "layout": layout}
    from app.pipeline.context import null_context
    res = render.render_clip(src, info, clip, words, {"caption_style": "classic"}, tmp_path, tmp_path, tmp_path,
                             null_context())
    out = ffmpeg.probe(res["output_path"])
    assert (out.width, out.height, out.video_codec, out.audio_codec) == (1080, 1920, "h264", "aac")
    assert out.duration == pytest.approx(6.0, abs=0.3)
    assert res["thumb_path"]
    expected = {"follow": "follow", "split": "split", "fit": "fit", "speaker": "speaker"}[layout]
    assert res["render_info"]["layout"] == expected


def test_filtergraph_has_no_shell_metachar_injection():
    plan = {"layout": "center", "keyframes": [(0, 0.5)]}
    g = render.build_filtergraph([(0, 5)], plan, 1920, 1080, 30, None, 5)
    assert not re.search(r"[;&|`$]\s*(rm|del|curl)", g)
    assert "[vout]" in g and "[aout]" in g


def test_tiktok_pace_speed_and_cold_open_render(sample_two, tmp_path):
    """Ritmo TikTok + 1.1x + gancho: duração bate com a linha do tempo e o tema entra no ASS."""
    import pysubs2

    from app.pipeline import transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    clip = {"id": "eeeeeeeeeeee", "start": 0.45, "end": 30.5, "layout": "follow"}
    natural = render.render_clip(src, info, clip | {"id": "ffffffffffff"}, words, {"pace": "natural"},
                                 tmp_path, tmp_path, tmp_path, null_context())
    fast = render.render_clip(src, info, clip, words,
                              {"pace": "tiktok", "speed": 1.1, "cold_open": True, "theme_text": "TEMA\nDO VÍDEO"},
                              tmp_path, tmp_path, tmp_path, null_context())
    ri = fast["render_info"]
    assert ri["cold_open"] and ri["speed"] == 1.1 and ri["removed_pause_s"] > natural["render_info"]["removed_pause_s"]
    hook_len = (ri["cold_open"][1] - ri["cold_open"][0]) / 1.1
    main_natural = natural["duration"]
    assert fast["duration"] < main_natural / 1.1 + hook_len + 0.3  # cortou respirações além da aceleração
    subs = pysubs2.load(str(tmp_path / "eeeeeeeeeeee.ass"))
    theme = [e for e in subs if e.style == "Theme"]
    assert theme and "TEMA\\NDO VÍDEO" in theme[0].text and theme[0].start == 0
    first_caption = min((e for e in subs if e.style == "Caption"), key=lambda e: e.start)
    assert first_caption.start / 1000 < 0.5  # o gancho já começa falando


def test_snap_intervals_on_frame_grid():
    snapped = render.snap_intervals([(0.0, 1.234), (2.01, 3.0)], 30)
    for a, b in snapped:
        assert abs(a * 30 - round(a * 30)) < 1e-4 and abs(b * 30 - round(b * 30)) < 1e-4
    assert render.TimeMap([(0, 2), (3, 5)], 2.0).duration == pytest.approx(2.0)
