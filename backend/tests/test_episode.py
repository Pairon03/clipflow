"""Mapa do episódio (blocos de assunto/história) e séries Parte 1, 2…"""
import json

import pytest
from fastapi.testclient import TestClient

from app import db, storage
from app.pipeline import episode, selection, series, transcribe
from test_selection import make_transcript

# três assuntos bem diferentes, com uma pausa longa e uma frase que abre história entre eles
FOOTBALL = [
    "O time jogou muito mal no campeonato e o técnico errou na escalação do meio de campo.",
    "O atacante perdeu três gols na frente do goleiro e a torcida vaiou o time inteiro no estádio.",
    "Na minha opinião o técnico precisa mudar o esquema tático antes da final do campeonato.",
] * 4
STORY = [
    "Deixa eu te contar uma história que aconteceu comigo no aeroporto.",
    "Eu cheguei atrasado, peguei a fila errada e o segurança olhou pra mim desconfiado.",
    "Aí ele falou assim: o senhor vai ter que me acompanhar até a sala do fundo.",
    "Eu gelei, fiquei sem entender nada e pensei que ia perder o voo.",
    "Quando eu entrei na sala tinha dois policiais me esperando com a minha mala aberta.",
    "Só que de repente um deles começou a rir e falou que era meu primo me pregando uma peça.",
    "Eu nunca vou esquecer aquele dia, quase morri de susto no aeroporto.",
] * 3
SPONSOR = [
    "Esse episódio tem o patrocínio da loja parceira, use o cupom podcast dez.",
    "Se inscreve no canal, ativa o sininho e deixa o like pra ajudar o programa.",
] * 4


def _transcript(*groups, pause=3.0):
    t, segs = 1.0, []
    for g in groups:
        tr = make_transcript(g, gap=1.1)
        for s in tr["segments"]:
            off = t - tr["segments"][0]["start"]
            segs.append({**s, "start": s["start"] + off, "end": s["end"] + off,
                         "words": [{**w, "start": w["start"] + off, "end": w["end"] + off} for w in s["words"]]})
        t = segs[-1]["end"] + pause
    return {"engine": "test", "language": "pt", "duration": t, "segments": segs}


def test_map_splits_topics_and_ranks_story_above_sponsor():
    tr = _transcript(SPONSOR, FOOTBALL, STORY)
    blocks = episode.build(tr)
    assert len(blocks) >= 3
    assert blocks[0].start <= tr["segments"][0]["start"] + 0.1                      # cobre o episódio inteiro
    assert abs(blocks[-1].end - tr["segments"][-1]["end"]) < 0.1
    assert all(b.duration >= episode.MIN_BLOCK_S - 0.01 for b in blocks)
    story_start = next(s["start"] for s in tr["segments"] if s["text"].startswith("Deixa eu te contar"))
    assert any(abs(b.start - story_start) < 0.5 for b in blocks)                   # a história abre um bloco
    story = max(blocks, key=lambda b: b.score)
    assert story.kind == "História" and story.start >= story_start - 0.5
    sponsor = blocks[0]
    assert sponsor.kind == "Propaganda/chamada" and sponsor.score == min(b.score for b in blocks)
    assert {round(b.score) for b in blocks} >= {0, 100}                            # usa a escala inteira


def test_clips_come_from_the_best_block_and_do_not_cross_topics():
    tr = _transcript(SPONSOR, FOOTBALL, STORY)
    blocks = episode.build(tr)
    chosen, _ = selection.find_clips(tr, 1, 20, 45, blocks=blocks)
    best = max(blocks, key=lambda b: b.score)
    c = chosen[0]
    assert c.block == best.index and best.start - 0.5 <= c.start and c.end <= best.end + 0.5
    assert any(r.startswith("Bloco:") for r in c.reasons)


def test_map_save_and_load_roundtrip(tmp_path):
    tr = _transcript(FOOTBALL, STORY)
    blocks = episode.build(tr)
    episode.save(tmp_path / "m.json", blocks, 123.0, ai=False)
    back = episode.load(tmp_path / "m.json", 123.0)
    assert [(b.start, b.end, b.title) for b in back] == [(round(b.start, 2), round(b.end, 2), b.title) for b in blocks]
    assert episode.load(tmp_path / "m.json", 999.0) is None                       # transcrição mudou
    assert episode.load(tmp_path / "m.json", 123.0, need_ai=True) is None          # pediu IA, mapa sem IA


def _sents(texts, gap=0.6, wps=2.8):
    return selection.build_sentences(transcribe.all_words(make_transcript(texts, gap, wps)))


def test_series_parts_end_on_suspense_and_recap_previous_line():
    sents = _sents(STORY)
    total = sents[-1].end - sents[0].start
    parts = series.plan(sents, 20, 45)
    assert 2 <= len(parts) <= series.MAX_PARTS
    assert parts[0]["start"] == sents[0].start and parts[-1]["end"] == sents[-1].end
    for k, p in enumerate(parts):
        assert p["end"] - p["start"] <= 45 + 0.01
        if k:
            prev_last = sents[parts[k - 1]["last"]]
            assert p["recap"] == (prev_last.start, prev_last.end)                  # retomada com fala real
            assert p["first"] == parts[k - 1]["last"] + 1
    assert all(p["cliff"] is not None for p in parts[:-1]) and parts[-1]["cliff"] is None
    assert total > 45
    assert series.plan(sents[:3], 20, 45) == []                                    # cabe em um corte: sem série


def test_cut_quality_prefers_questions_and_turns():
    sents = _sents(["Eu cheguei na sala e vi uma coisa estranha.", "Sabe o que tinha lá dentro?",
                    "Aí ele abriu a porta devagar.", "E a mala estava aberta e"])
    assert series.cut_quality(sents, 1) > series.cut_quality(sents, 0)             # pergunta antes da virada
    assert series.cut_quality(sents, 3) < 0                                        # termina em "e"


def test_series_only_for_strong_long_stories():
    sents = _sents(STORY, gap=1.1)
    parts = series.plan(sents, 20, 45)
    b = episode.Block(0, sents[0].start, sents[-1].end, sents, score=90, kind="História")
    assert series.worth_it(b, parts, 45)[0]
    weak = episode.Block(0, b.start, b.end, sents, score=50, kind="História")
    assert not series.worth_it(weak, parts, 45)[0]
    chat = episode.Block(0, b.start, b.end, sents, score=90, kind="Conversa")
    assert not series.worth_it(chat, parts, 45)[0]
    no_end = episode.Block(0, b.start, b.end, sents, score=90, kind="História",
                           ai={"nota": 85, "tem_desfecho": False})
    assert not series.worth_it(no_end, parts, 45)[0]                               # IA: sem desfecho


def test_part_titles_and_descriptions():
    assert series.part_title("O dia do aeroporto", 2, 3) == "O dia do aeroporto (Parte 2/3)"
    assert series.part_title("O dia do aeroporto (Parte 1/3)", 3, 3) == "O dia do aeroporto (Parte 3/3)"
    assert len(series.part_title("x" * 200, 1, 2)) == 100
    assert "próximo vídeo" in series.part_description("desc", 1, 3)
    assert "Parte final" in series.part_description("desc", 3, 3)


@pytest.fixture()
def project_with_story():
    from app.pipeline import runner

    tr = _transcript(SPONSOR, FOOTBALL, STORY, FOOTBALL)
    pid = db.new_id()
    now = db.now()
    db.execute("INSERT INTO projects (id, name, status, source_type, rights_basis, rights_confirmed_at, options_json, "
               "created_at, updated_at) VALUES (?, 'Mapa', 'awaiting_review', 'upload', 'own', ?, ?, ?, ?)",
               (pid, now, json.dumps({"count": 2, "min_duration": 20, "max_duration": 45, "series": True}), now, now))
    runner.transcript_path(pid).write_text(json.dumps(tr), encoding="utf-8")
    return pid, tr


def test_auto_series_and_map_api(project_with_story):
    from app.main import create_app
    from app.pipeline import runner

    pid, tr = project_with_story
    opts = {"count": 2, "min_duration": 20, "max_duration": 45, "series": True}
    runner.select_clips(pid, tr, opts)
    clips = db.fetch_all("SELECT * FROM clips WHERE project_id = ? AND selected = 1 ORDER BY start", (pid,))
    parts = [c for c in clips if c["series"]]
    assert len(parts) >= 2                                                         # a história virou série
    assert [c["series"]["part"] for c in parts] == list(range(1, len(parts) + 1))
    assert all(c["block_index"] is not None for c in clips)
    s0, e0 = parts[0]["series"]["story"]
    assert not [c for c in clips if not c["series"] and c["start"] < e0 and c["end"] > s0]   # sem corte repetido
    assert runner.map_path(pid).exists()

    with TestClient(create_app(start_worker=False)) as client:
        m = client.get(f"/api/projects/{pid}/map").json()
        assert m["blocks"] and m["max_duration"] == 45
        story = next(b for b in m["blocks"] if b["index"] == parts[0]["series"]["block"])
        assert story["kind"] == "História" and len(story["clips"]) == len(parts)
        foot = next(b for b in m["blocks"] if b["kind"] != "Propaganda/chamada" and b["index"] != story["index"])
        r = client.post(f"/api/projects/{pid}/map/{foot['index']}/clip")
        assert r.status_code == 200
        new = db.fetch_one("SELECT * FROM clips WHERE id = ?", (r.json()["clip_id"],))
        assert new["selected"] == 1 and foot["start"] - 0.5 <= new["start"] and new["end"] <= foot["end"] + 0.5
        r = client.post(f"/api/projects/{pid}/map/{story['index']}/series")          # refaz a série
        assert r.status_code == 200
        again = db.fetch_all("SELECT id FROM clips WHERE project_id = ? AND series_json IS NOT NULL", (pid,))
        assert len(again) == len(r.json()["clip_ids"])                              # a antiga foi trocada
        assert client.post(f"/api/projects/{pid}/map/999/clip").status_code == 404

    opts["series"] = False
    runner.select_clips(pid, tr, opts)
    assert not db.fetch_all("SELECT id FROM clips WHERE project_id = ? AND series_json IS NOT NULL "
                            "AND status != 'done'", (pid,))


def test_series_tag_drawn_on_title_png(tmp_path):
    from PIL import Image

    from app.pipeline import overlay

    out = overlay.add_series_tag(None, "PARTE 2/3", tmp_path / "t.png", 1080, 1920)
    with Image.open(out) as im:
        bbox = im.getchannel("A").getbbox()
        assert bbox and bbox[2] <= 1080 - 60 and bbox[1] >= int(1920 * 0.08)
        r, g, b, a = im.getpixel(((bbox[0] + bbox[2]) // 2, bbox[1] + 4))
        assert r > 200 and g < 80 and a > 200                                      # tarja vermelha
    card = overlay.render_card("caixa", {"lead": "Fulano diz:", "quote": "Ele contou tudo"}, tmp_path / "c.png", 1080, 1920)
    with Image.open(card) as im:
        card_bottom = im.getchannel("A").getbbox()[3]
    out = overlay.add_series_tag(card, "PARTE 1/2", tmp_path / "c.png", 1080, 1920)
    with Image.open(out) as im:
        tag_top = Image.Image.getbbox(im.crop((540, card_bottom, 1080, 1920)).getchannel("A"))
        assert tag_top is not None                                                  # tarja logo abaixo do título
    assert storage  # módulo usado pelo fixture do runner


def test_series_label_rendered_in_video(sample_two, tmp_path):
    from PIL import Image

    from app.pipeline import ffmpeg, render
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 20.5)
    clip = {"start": 0.45, "end": 20.5, "layout": "center", "id": "serie0000001"}
    res = render.render_clip(src, info, clip, words, {"captions": False, "series_label": "PARTE 2/3"},
                             tmp_path, tmp_path, tmp_path, null_context())
    frame = tmp_path / "f.png"
    ffmpeg.run(["-ss", "8", "-i", res["output_path"], "-frames:v", "1", str(frame)])
    with Image.open(frame) as im:
        im = im.convert("RGB")
        w, h = im.size
        reds = sum(1 for x in range(w // 2, w, 4) for y in range(int(h * 0.07), int(h * 0.16), 4)
                   if (lambda p: p[0] > 190 and p[1] < 90 and p[2] < 90)(im.getpixel((x, y))))
    assert reds > 50                                                               # tarja visível o vídeo todo
