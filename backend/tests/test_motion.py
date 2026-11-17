"""Explicação animada (motion graphics): roteiro pela fala, desenho dos blocos e render com teaser e bolha."""
import json

import numpy as np
import pytest
from PIL import Image

from app.api.common import validate_options
from app.pipeline import ffmpeg, motion, render

TEXT = [
    (2.4, 3.1, "E, porque assim,"), (3.2, 4.1, "o moleque naquela"), (4.1, 5.2, "época, ele já era"),
    (5.2, 5.9, "uma máquina de fazer"), (5.9, 6.5, "dinheiro, né?"), (7.0, 9.4, "Então falou, agora vamos."),
    (9.5, 11.4, "Então, mas quando o Neymar"), (11.5, 12.4, "é vendido,"), (12.5, 14.9, "foi feito um trabalho,"),
    (15.0, 17.0, "o Neymar começou cedo,"), (19.3, 22.6, "Esse moleque, esse moleque."),
    (23.1, 24.4, "Já era campeão da libertadores."), (27.1, 28.7, "Nós chegamos a duas"),
    (28.7, 30.2, "quartas de finais com"), (30.3, 32.9, "ele na copa,"), (32.9, 33.8, "foi Bélgica,"),
    (33.9, 35.8, "quarta de final e..."), (35.8, 36.8, "Croácia a quarta de"), (37.0, 38.2, "Depois que ele saiu,"),
    (38.3, 39.5, "esquece, a gente parou"), (40.2, 41.3, "antes das oitavas,"), (42.1, 43.6, "nem lembro aqui,"),
    (48.1, 49.4, "é só olhar para a seleção"), (49.5, 50.0, "sem o Neymar hoje,"), (59.9, 61.4, "um time comum, comum."),
]


def _words():
    out = []
    for a, b, txt in TEXT:
        ws = txt.split()
        step = (b - a) / len(ws)
        out += [{"text": w, "start": a + i * step, "end": a + (i + 1) * step - 0.02} for i, w in enumerate(ws)]
    return out


def test_options_default_off_and_preferences_keys():
    o = validate_options({})
    assert (o["motion"], o["motion_teaser"], o["motion_bubble"]) == ("nenhum", True, True)
    assert validate_options({"motion": "inicio"})["motion"] == "inicio"
    with pytest.raises(Exception):
        validate_options({"motion": "sempre"})


def test_plan_picks_visual_moments_and_uses_only_speech():
    words = _words()
    full = " ".join(w["text"] for w in words).upper()
    blocks = motion.plan(words, 62.0, "auto")
    assert 1 <= len(blocks) <= 3
    for a, b in zip(blocks, blocks[1:]):
        assert b["start"] - a["end"] >= motion.MIN_GAP_S                     # podcast entre os blocos
    for b in blocks:
        assert motion.MIN_BLOCK_S <= b["end"] - b["start"] <= motion.MAX_BLOCK_S + 0.01
        for sc in b["scenes"]:
            for txt in [sc["title"], sc["highlight"]] + [i["text"] for i in sc["items"]]:
                for word in txt.split():
                    assert word in full.replace(",", "").replace(".", ""), word  # nada inventado
    cards = [sc for b in blocks for sc in b["scenes"] if sc["kind"] == "cartoes"]
    assert cards and [i["text"] for i in cards[0]["items"]] == ["BÉLGICA", "CROÁCIA"]
    first = motion.plan(words, 62.0, "inicio")[0]
    assert first["start"] == pytest.approx(2.4, abs=0.01)                     # abre o corte
    assert motion.plan(words, 62.0, "nenhum") == []


def test_validate_blocks_from_editor():
    raw = [{"start": -3, "end": 6, "scenes": [{"kind": "xyz", "at": 1, "title": "x" * 40, "icon": "naoexiste",
                                                "items": [{"text": "a", "at": 99}]}]},
           {"start": 10, "end": 10.5, "scenes": []}]
    out = motion.validate_blocks(raw, 30)
    assert len(out) == 1 and out[0]["start"] == 0
    sc = out[0]["scenes"][0]
    assert sc["kind"] == "destaque" and len(sc["title"]) == 24 and sc["icon"] == motion.DEFAULT_ICON
    assert sc["items"][0]["at"] <= 6
    # campos vazios do editor (input numérico apagado) não derrubam a API
    odd = motion.validate_blocks([{"start": "", "end": 5}, {"start": 1, "end": 6, "scenes": [
        {"at": "", "items": [{"text": "A", "at": None}, "x"]}, "lixo"]}], 30)
    assert len(odd) == 1 and odd[0]["scenes"][0]["at"] == 1 and len(odd[0]["scenes"][0]["items"]) == 1
    moved = motion.shift_blocks(out, -1.0, 29)                                  # corte começou 1 s depois
    assert moved[0]["end"] == 5 and moved[0]["scenes"][0]["at"] == 0


def _frame(path, at, tmp_path, name):
    out = tmp_path / name
    ffmpeg.run(["-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", str(out)])
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def test_render_block_draws_scenes_with_transparent_reveal(tmp_path):
    blk = {"start": 0.0, "end": 6.0, "scenes": [
        {"kind": "numero", "at": 0.0, "title": "NÓS CHEGAMOS A", "number": "2", "highlight": "QUARTAS", "items": []},
        {"kind": "cartoes", "at": 3.0, "title": "QUARTAS", "icon": "flag",
         "items": [{"text": "BÉLGICA", "at": 3.4}, {"text": "CROÁCIA", "at": 4.4}]}]}
    path = motion.render_block(blk, tmp_path / "b.mov", 540, 960)
    info = ffmpeg.probe(path).as_dict()
    assert info["duration"] == pytest.approx(6.0, abs=0.1)
    mid = _frame(path, 2.0, tmp_path, "m.png")
    assert (np.abs(mid[480, 20] - motion.THEME["bg"]) < 12).all()            # fundo claro do tema
    navy = (np.abs(mid - motion.THEME["navy"]).sum(axis=2) < 40).sum()
    assert navy > 2000                                                        # o "2" grande
    late = _frame(path, 5.2, tmp_path, "l.png")
    white = ((late > 250).all(axis=2)).sum()
    assert white > 20000                                                      # os dois cartões brancos


def test_render_with_motion_teaser_and_bubble(sample_two, tmp_path):
    from app.pipeline import transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    plan = [{"start": 8.0, "end": 15.0, "scenes": [
        {"kind": "destaque", "at": 8.0, "title": "O SEGREDO", "highlight": "REPETIÇÃO", "icon": "brain", "items": []}]}]
    clip = {"start": 0.45, "end": 30.5, "layout": "follow", "id": "motion000001"}
    opts = {"motion_mode": "auto", "motion_plan": plan, "motion_teaser": True, "motion_bubble": True}
    res = render.render_clip(src, info, clip, words, opts, tmp_path, tmp_path, tmp_path, null_context())
    m = res["render_info"]["motion"]
    assert m["mode"] == "auto" and m["teaser"] and m["blocks"] == plan
    plain = render.render_clip(src, info, clip | {"id": "motion000002"}, words, {}, tmp_path, tmp_path, tmp_path,
                               null_context())
    assert plain["render_info"]["motion"]["mode"] is None
    assert res["duration"] == pytest.approx(plain["duration"], abs=0.1)
    bg = np.array(motion.THEME["bg"])

    def light_bg(fr):
        return (np.abs(fr[150:250:10, 20:150:10] - bg).sum(axis=2) < 45).mean()

    assert light_bg(_frame(res["output_path"], 0.4, tmp_path, "t.png")) > 0.8        # teaser no começo
    assert light_bg(_frame(res["output_path"], 3.0, tmp_path, "p.png")) < 0.2        # depois, o podcast
    inside = _frame(res["output_path"], 11.0, tmp_path, "i.png")
    assert light_bg(inside) > 0.8                                                    # bloco animado
    y = int(1920 * 0.735) + motion.BUBBLE // 2
    assert (np.abs(inside[y, 540] - bg).sum()) > 60                                  # rosto na bolha
    assert light_bg(_frame(res["output_path"], res["duration"] - 1.5, tmp_path, "e.png")) < 0.2


def test_motion_api_get_and_edit():
    from fastapi.testclient import TestClient

    from app import db
    from app.main import create_app
    from app.pipeline import runner

    pid, cid = db.new_id(), db.new_id()
    now = db.now()
    db.execute("INSERT INTO projects (id, name, status, source_type, rights_basis, rights_confirmed_at, options_json, "
               "created_at, updated_at) VALUES (?, 'M', 'awaiting_review', 'upload', 'own', ?, ?, ?, ?)",
               (pid, now, json.dumps({"motion": "auto"}), now, now))
    words = _words()
    db.execute("INSERT INTO clips (id, project_id, start, end, text, words_json, created_at) VALUES (?, ?, 0, 62, ?, ?, ?)",
               (cid, pid, " ".join(w["text"] for w in words), json.dumps(words), now))
    with TestClient(create_app(start_worker=False)) as client:
        v = client.get(f"/api/clips/{cid}/motion").json()
        assert v["effective"] == "auto" and v["blocks"] and not v["edited"] and "trophy" in v["icons"]
        edited = v["blocks"][:1]
        edited[0]["scenes"][0]["title"] = "MEU TÍTULO"
        r = client.put(f"/api/clips/{cid}/motion", json={"mode": "inicio", "blocks": edited}).json()
        assert r["edited"] and r["mode"] == "inicio" and r["blocks"][0]["scenes"][0]["title"] == "MEU TÍTULO"
        clip = db.fetch_one("SELECT * FROM clips WHERE id = ?", (cid,))
        o = runner._clip_options({"motion": "auto"}, {"card": {}}, clip, 0)
        assert o["motion_mode"] == "inicio" and o["motion_plan"][0]["scenes"][0]["title"] == "MEU TÍTULO"
        client.put(f"/api/clips/{cid}/motion", json={"mode": "off"})
        clip = db.fetch_one("SELECT * FROM clips WHERE id = ?", (cid,))
        assert runner._clip_options({"motion": "auto"}, {"card": {}}, clip, 0)["motion_mode"] == "nenhum"
        assert client.put(f"/api/clips/{cid}/motion", json={"mode": "x"}).status_code == 422


def test_llm_refine_keeps_only_speech_words(monkeypatch):
    from app.pipeline import llm

    words = _words()
    base = motion.plan(words, 62.0, "auto")
    seen = []

    def fake(prompt, system, schema=None, **k):
        n = schema["properties"]["cenas"]["minItems"]
        first = prompt.split("[0] ")[1].split("\n")[0].replace(",", "").split()
        seen.append(first)
        cenas = [{"tipo": "destaque", "titulo": " ".join(first[-2:]), "destaque": "", "numero": "", "itens": [],
                  "icone": "trophy"}] + [{"tipo": "destaque", "titulo": "Messi inventado", "destaque": "", "numero": "",
                                          "itens": [], "icone": "star"}] * (n - 1)
        return {"cenas": cenas}

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "generate_json", fake)
    refined = motion.plan(words, 62.0, "auto", use_llm=True)
    assert [(b["start"], b["end"]) for b in refined] == [(b["start"], b["end"]) for b in base]
    titles = [sc["title"] for b in refined for sc in b["scenes"]]
    assert " ".join(seen[0][-2:]).upper()[:24] in titles and not any("MESSI" in t for t in titles)          # o inventado é descartado
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: None)              # Ollama fora do ar
    assert motion.plan(words, 62.0, "auto", use_llm=True) == base
