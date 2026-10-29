"""Estilo viral (opcional): manchete, entrada com movimento, troca de enquadramento por frase e chamada final."""
from PIL import Image

from app.api.common import validate_options
from app.pipeline import ffmpeg, render, viral


def test_options_are_off_by_default():
    o = validate_options({})
    assert (o["viral_headline"], o["intro_punch"], o["dynamism"], o["end_cta"]) == (False, False, "nenhum", False)
    assert validate_options({"dynamism": "alto"})["dynamism"] == "alto"


def test_headline_uses_real_speech_only():
    card = {"question": "Por que a família não é só sangue?", "quote": "eu já fui corno também",
            "headline": "Fulano diz: “Uma frase da manchete”", "topic_line": "Fulano sobre futebol"}
    assert viral.headline_text(card) == "POR QUE A FAMÍLIA NÃO É SÓ SANGUE?"
    assert viral.headline_text({"headline": "Fulano diz: “Uma frase da manchete”"}) == "UMA FRASE DA MANCHETE"
    long_q = {"question": "Você acha que dá pra viver de música no Brasil hoje em dia sem gravadora nenhuma?",
              "quote": "Ninguém vive de música"}
    assert viral.headline_text(long_q) == "NINGUÉM VIVE DE MÚSICA"          # não corta fala no meio
    assert viral.headline_text({}) is None
    assert viral.cta_text("Opinião") == "VOCÊ CONCORDA?\nCOMENTA AQUI"
    assert viral.cta_text("História", 1, 3) == "CONTINUA NA\nPARTE 2"


def test_angle_changes_follow_sentences():
    words, t = [], 0.0
    for i in range(60):
        txt = "palavra." if i % 6 == 5 else "palavra"
        words.append({"text": txt, "start": t, "end": t + 0.35})
        t += 0.4
    ch = viral.angle_changes(words, t, "medio")
    assert ch and all(b - a >= viral.DYNAMISM["medio"][0] - 1e-6 for a, b in zip(ch, ch[1:]))
    assert len(viral.angle_changes(words, t, "alto")) > len(ch)
    assert viral.angle_changes(words, t, "nenhum") == []
    z, x, y = viral.framing_exprs(ch, "medio")
    assert z.startswith("if(gte(t,") and "1.16" in z


def test_big_text_png(tmp_path):
    p = viral.big_text_png("VOCÊ CONCORDA?\nCOMENTA AQUI", tmp_path / "c.png", 1080, 1920)
    with Image.open(p) as im:
        box = im.getchannel("A").getbbox()
    assert box and box[0] >= 30 and box[2] <= 1050 and box[3] < 1920 * 0.45


def test_render_with_viral_style(sample_two, tmp_path):
    from app.pipeline import transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    clip = {"start": 0.45, "end": 30.5, "layout": "follow", "id": "viral0000001"}
    opts = {"viral_headline": True, "viral_headline_text": "ISSO MUDOU TUDO?", "intro_punch": True,
            "dynamism": "alto", "end_cta": True, "cta_text": "VOCÊ CONCORDA?\nCOMENTA AQUI", "sfx": "sutil",
            "title_style_resolved": "caixa", "title_card": {"lead": "Ele diz:", "quote": "Uma frase"}}
    res = render.render_clip(src, info, clip, words, opts, tmp_path, tmp_path, tmp_path, null_context())
    v = res["render_info"]["viral"]
    assert v["headline"] and v["cta"] and v["intro_punch"] and v["angle_changes"] >= 2
    plain = render.render_clip(src, info, clip | {"id": "viral0000002"}, words, {}, tmp_path, tmp_path, tmp_path,
                               null_context())
    assert plain["render_info"]["viral"] == {"headline": None, "cta": None, "intro_punch": False,
                                             "dynamism": None, "angle_changes": 0}

    def frame(path, at, name):
        out = tmp_path / name
        ffmpeg.run(["-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", str(out)])
        return Image.open(out).convert("RGB")

    def yellow(im):
        w, h = im.size
        return sum(1 for x in range(0, w, 6) for y in range(int(h * 0.12), int(h * 0.42), 6)
                   if (lambda p: p[0] > 220 and p[1] > 180 and p[2] < 60)(im.getpixel((x, y))))

    d = res["duration"]
    assert yellow(frame(res["output_path"], 1.2, "h.png")) > 150             # manchete no começo
    assert yellow(frame(res["output_path"], d - 1.2, "c.png")) > 150          # chamada no fim
    assert yellow(frame(res["output_path"], d / 2, "m.png")) < 40             # no meio, nenhuma das duas
    assert abs(res["duration"] - plain["duration"]) < 0.1                     # mesma duração e áudio


def test_clip_headline_override_and_preferences():
    import json

    from fastapi.testclient import TestClient

    from app import db
    from app.main import create_app
    from app.pipeline import runner

    pid, cid = db.new_id(), db.new_id()
    now = db.now()
    db.execute("INSERT INTO projects (id, name, status, source_type, rights_basis, rights_confirmed_at, options_json, "
               "created_at, updated_at) VALUES (?, 'V', 'awaiting_review', 'upload', 'own', ?, ?, ?, ?)",
               (pid, now, json.dumps({"viral_headline": True, "end_cta": True}), now, now))
    db.execute("INSERT INTO clips (id, project_id, start, end, text, category, created_at) VALUES (?, ?, 0, 40, ?, "
               "'Opinião', ?)", (cid, pid, "Você acha que dá pra ficar rico? Eu acho que dá sim, trabalhando muito.", now))
    with TestClient(create_app(start_worker=False)) as client:
        auto = client.get(f"/api/clips/{cid}/headline").json()
        assert auto["auto"] == "VOCÊ ACHA QUE DÁ PRA FICAR RICO?" and auto["custom"] is None
        assert client.patch(f"/api/clips/{cid}", json={"headline": "Ficar rico é possível"}).status_code == 200
        clip = db.fetch_one("SELECT * FROM clips WHERE id = ?", (cid,))
        opts = runner._clip_options({"viral_headline": True, "end_cta": True}, {"card": {}}, clip, 0)
        assert opts["viral_headline_text"] == "FICAR RICO É POSSÍVEL" and opts["cta_text"].startswith("VOCÊ CONCORDA?")
        client.patch(f"/api/clips/{cid}", json={"headline": ""})
        assert db.fetch_one("SELECT headline FROM clips WHERE id = ?", (cid,))["headline"] is None
        r = client.put("/api/preferences", json={"options": {"viral_headline": True, "dynamism": "medio"}})
        assert r.json()["options"]["dynamism"] == "medio" and r.json()["options"]["end_cta"] is False
        client.delete("/api/preferences")
    off = runner._clip_options({}, {"card": {"question": "Isso funciona mesmo?"}}, clip, 0)
    assert "viral_headline_text" not in off and "cta_text" not in off
