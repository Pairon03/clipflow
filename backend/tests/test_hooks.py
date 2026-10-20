"""Ganchos com payoff: candidatos, 7 critérios, payoff, IA local (simulada), escolha manual e repetição no render."""
import json
import re
from pathlib import Path

import pytest

from app import config, db
from app.pipeline import hooks, llm, render
from app.pipeline.textutil import norm

STORIES = {s["id"]: s for s in json.loads((Path(__file__).parent / "data" / "hook_stories.json").read_text("utf-8"))}


def words_from(text: str) -> list[dict]:
    """Palavras com tempo realista (~2,8 palavras/s, pausas em pontuação), como sairiam do Whisper."""
    out, t = [], 0.4
    for tok in text.split():
        dur = max(0.14, len(tok) / 17)
        out.append({"text": tok, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur + 0.04 + (0.35 if re.search(r"[.!?]$", tok) else 0.12 if tok.endswith(",") else 0)
    return out


def story(sid):
    w = words_from(STORIES[sid]["text"])
    return w, w[0]["start"] - 0.2, w[-1]["end"] + 0.3


def chosen_text(r):
    return r["candidates"][r["chosen"]]["clean"] if r["chosen"] is not None else None


def test_candidates_are_literal_and_trimmed():
    w, s0, s1 = story("aeroporto")
    full = norm(" ".join(x["text"] for x in w))
    cands = hooks.candidates(w)
    assert len(cands) >= 6
    for c in cands:
        assert hooks.MIN_S <= c["end"] - c["start"] <= hooks.MAX_S
        assert norm(c["text"]) in full                       # trecho literal da fala, nada inventado
        assert norm(c["text"]).split()[0] not in {"e", "ai", "ne", "cara", "tipo", "entao"}  # sem muleta no começo


def test_long_sentences_are_cut_only_at_phrase_boundaries():
    w, _, _ = story("genro")
    cut = [c["clean"] for c in hooks.candidates(w) if not c["sentence_end"] and "chinelo" in c["clean"]]
    assert cut and cut[0].endswith("em casamento")              # não "…na frente de todo" (sem o "mundo")
    w, _, _ = story("falencia")
    assert not any(norm(c["clean"]).endswith(("vinte", "com")) for c in hooks.candidates(w))
    w, _, _ = story("aeroporto")
    assert not any(norm(c["clean"]).rstrip(".:").endswith(("fala", "fala assim")) for c in hooks.candidates(w))


@pytest.mark.parametrize("sid,good", [("falencia", "trezentos mil reais"), ("pai", "cadeira dele tava vazia")])
def test_heuristic_finds_the_intriguing_line(sid, good):
    w, s0, s1 = story(sid)
    r = hooks.analyze(w, s0, s1, use_llm=False)
    assert r["engine"] == "heuristica" and good in norm(chosen_text(r))
    assert len(r["candidates"]) >= 3                       # pelo menos três opções quando há material


def test_payoff_rules_hold_for_every_candidate():
    for sid in ("aeroporto", "falencia", "genro", "pai", "dividas", "spoiler"):
        w, s0, s1 = story(sid)
        r = hooks.analyze(w, s0, s1, use_llm=False)
        cands = r["candidates"]
        for i, c in enumerate(cands):
            assert c["payoff"]["ok"]
            assert c["start"] - s0 >= max(hooks.MIN_CONTEXT_S, min(0.25 * (s1 - s0), hooks.MAX_CONTEXT_S)) - 0.01
            assert s1 - c["end"] >= hooks.MIN_AFTER_S                 # há conclusão depois da frase
            assert (c["end"] - s0) / (s1 - s0) <= hooks.MAX_POSITION  # nada do trecho final (entregaria a resolução)
            for other in cands[i + 1:]:
                assert not hooks._overlaps(c, other)


def test_no_hook_when_story_is_too_short_or_ending_would_be_spoiled():
    w, s0, s1 = story("curto")
    r = hooks.analyze(w, s0, s1, use_llm=False)
    assert r["chosen"] is None and "curto" in r["reason"]
    w, s0, s1 = story("spoiler")
    r = hooks.analyze(w, s0, s1, use_llm=False)
    assert all("no final eu ganhei" not in norm(c["clean"]) for c in r["candidates"])


def test_reversal_lowers_fidelity():
    """'Eu ia desistir na semifinal' seguido de 'mas…' mudaria de sentido sozinho."""
    w, s0, s1 = story("spoiler")
    # frases curtas ficam inteiras ("…semifinal, mas a minha mãe…"), então o corte antes do "mas" nem é gerado
    assert not any(norm(c["clean"]).rstrip(".,").endswith("semifinal") for c in hooks.candidates(w))
    i = next(k for k, x in enumerate(w) if x["text"] == "desistir") - 2
    span = w[i:i + 5]                                           # "Eu ia desistir na semifinal,"
    c = {"start": span[0]["start"], "end": span[-1]["end"], "text": " ".join(x["text"] for x in span),
         "clean": "Eu ia desistir na semifinal.", "sentence_end": False}
    h = hooks.heuristic_scores(c, w, s0, s1, set())
    assert h["scores"]["fidelidade"] <= 6


def test_ai_scores_are_blended_and_spoiler_penalized(monkeypatch):
    w, s0, s1 = story("genro")
    base = hooks.analyze(w, s0, s1, use_llm=False)
    target = next(i for i, c in enumerate(base["candidates"]) if "chinelo" in norm(c["clean"]))

    def fake_eval(text, cands, timeout=None):
        assert all(norm(c["text"]) for c in cands)
        out = {}
        for c in cands:
            hi = "chinelo" in norm(c["text"])
            out[c["id"]] = {"scores": dict.fromkeys(hooks.CRITERIA, 9.5 if hi else 3.0), "spoiler": False,
                            "motivo": "cena inesperada" if hi else "narração comum"}
        return out

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "evaluate_hooks", fake_eval)
    r = hooks.analyze(w, s0, s1, use_llm=True)
    assert r["engine"] == "ollama+heuristica"
    best = r["candidates"][r["chosen"]]
    assert "chinelo" in norm(best["clean"]) and best["reason_ai"] == "cena inesperada"
    h = base["candidates"][target]["heuristic"]
    assert best["scores"]["curiosidade"] == pytest.approx(0.6 * 9.5 + 0.4 * h["curiosidade"], abs=0.01)


def test_ai_failure_falls_back_to_heuristic(monkeypatch):
    w, s0, s1 = story("falencia")
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: None)      # Ollama fora do ar / tempo esgotado
    r = hooks.analyze(w, s0, s1, use_llm=True)
    assert r["engine"] == "heuristica" and "indisponível" in r["reason"]
    assert "trezentos mil reais" in norm(chosen_text(r))


def test_evaluate_hooks_validates_model_output(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    cands = [{"id": i, "text": f"frase {i}"} for i in range(3)]
    good = {"a": [{"id": 0, "n": [8, 7, 6, 9, 7, 9, 8], "spoiler": False, "m": "bom"},
                  {"id": 1, "n": [3, 7, 2, 6, 4, 9, 5], "m": "comum"},
                  {"id": 2, "n": [6, 6, 6, 6, 6, 6, 6], "spoiler": True, "m": "entrega o final"}]}
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: good)
    out = llm.evaluate_hooks("texto", cands)
    assert out[0]["scores"]["curiosidade"] == 8 and out[0]["scores"]["payoff"] == 8 and out[2]["spoiler"]
    # formato alternativo {"0": {...}} também é aceito
    alt = {str(i["id"]): {k: v for k, v in i.items() if k != "id"} for i in good["a"]}
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: alt)
    assert set(llm.evaluate_hooks("texto", cands)) == {0, 1, 2}
    # resposta incompleta, nota fora da escala ou id inexistente: descarta tudo (vale a heurística)
    for bad in ({"a": good["a"][:2]},
                {"a": good["a"][:2] + [{"id": 2, "n": [11, 7, 6, 9, 7, 9, 8]}]},
                {"a": good["a"][:2] + [{"id": 99, "n": [8, 7, 6, 9, 7, 9, 8]}]}):
        monkeypatch.setattr(llm, "generate_json", lambda *a, b=bad, **k: b)
        assert llm.evaluate_hooks("texto", cands) is None
    # notas iguais para todos não diferenciam nada: descarta
    same = {"a": [{"id": i, "n": [2] * 7} for i in range(3)]}
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: same)
    assert llm.evaluate_hooks("texto", cands) is None


def test_selected_respects_manual_choice_and_clip_changes():
    w, s0, s1 = story("pai")
    r = hooks.analyze(w, s0, s1, use_llm=False)
    auto = hooks.selected(r, s0, s1)
    best = r["candidates"][r["chosen"]]
    assert auto == (round(max(best["start"] - s0 - 0.05, 0), 3), round(best["end"] - s0 + 0.15, 3))
    other = 1 if r["chosen"] != 1 else 0
    assert hooks.selected(r | {"choice": other}, s0, s1)[0] == pytest.approx(r["candidates"][other]["start"] - s0 - 0.05,
                                                                               abs=0.002)
    assert hooks.selected(r | {"choice": "none"}, s0, s1) is None
    assert hooks.selected(r, s0 + 1, s1) is None and not hooks.is_current(r, s0 + 1, s1)


def test_hook_column_migration_and_ensure_hook_cache(monkeypatch):
    from app.pipeline import runner

    db.init()
    with db.conn() as c:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(clips)")}
    assert "hook_json" in cols
    calls = []
    real = hooks.analyze

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(hooks, "analyze", counting)
    w, s0, s1 = story("pai")
    clip = {"id": "nao-existe-no-db", "start": s0, "end": s1, "hook": None}
    first = runner.ensure_hook(clip, w, {"cold_open": True})
    second = runner.ensure_hook(clip, w, {"cold_open": True})
    assert first is second and len(calls) == 1                 # reaproveita enquanto o corte não muda
    assert runner.ensure_hook(clip, w, {"cold_open": False}) is None


def test_render_keeps_intentional_repetition(sample_two, tmp_path):
    """A frase do gancho abre o vídeo e volta no lugar original (payoff), com a mesma fala."""
    from app.pipeline import ffmpeg, transcribe
    from app.pipeline.context import null_context

    src = sample_two["video"]
    info = ffmpeg.probe(src).as_dict()
    t = transcribe.import_subtitles(sample_two["srt"], info["duration"])
    words = render.words_for_clip(transcribe.all_words(t), 0.45, 30.5)
    sent = [w for w in words if 12.0 <= w["start"] and w["end"] <= 15.0]
    interval = (round(sent[0]["start"] - 0.45 - 0.05, 3), round(sent[-1]["end"] - 0.45 + 0.15, 3))
    res = render.render_clip(src, info, {"id": "hookrep00001", "start": 0.45, "end": 30.5, "layout": "follow"}, words,
                             {"cold_open": True, "hook_interval": interval,
                              "hook_meta": {"text": "teste", "engine": "heuristica"}},
                             tmp_path, tmp_path, tmp_path, null_context())
    ri = res["render_info"]
    hook_out = ri["cold_open"][1] - ri["cold_open"][0]
    first = [w["text"] for w in res["words_out"] if w["start"] < hook_out]
    texts = [w["text"] for w in res["words_out"]]
    assert first == [w["text"] for w in sent]                  # 1ª ocorrência: o gancho
    later = [w for w in res["words_out"] if w["start"] >= hook_out]
    seq = [w["text"] for w in later]
    k = next(i for i in range(len(seq)) if seq[i:i + len(first)] == first)
    assert texts.count(first[0]) >= 2                          # a frase aparece de novo (payoff)
    assert later[k]["start"] == pytest.approx(ri["payoff_at"], abs=0.25)
    assert ri["hook"]["engine"] == "heuristica" and ri["payoff_at"] > hook_out + 5


def test_api_manual_hook_choice():
    from fastapi.testclient import TestClient

    from app.main import create_app

    w, s0, s1 = story("pai")
    hook = hooks.analyze(w, s0, s1, use_llm=False)
    pid, cid, now = db.new_id(), db.new_id(), db.now()
    db.execute("INSERT INTO projects (id, name, status, source_type, rights_basis, rights_confirmed_at, options_json, "
               "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
               (pid, "ganchos", "awaiting_review", "upload", "own", now, json.dumps({"cold_open": True}), now, now))
    db.execute("INSERT INTO clips (id, project_id, start, end, status, selected, created_at, hook_json) "
               "VALUES (?,?,?,?,?,?,?,?)", (cid, pid, s0, s1, "selected", 1, now, json.dumps(hook)))
    with TestClient(create_app(start_worker=False)) as client:
        r = client.patch(f"/api/clips/{cid}", json={"hook_choice": 1})
        assert r.status_code == 200 and r.json()["hook"]["choice"] == 1
        assert client.patch(f"/api/clips/{cid}", json={"hook_choice": 99}).status_code == 422
        assert client.patch(f"/api/clips/{cid}", json={"hook_choice": "talvez"}).status_code == 422
        assert client.patch(f"/api/clips/{cid}", json={"hook_choice": "none"}).json()["hook"]["choice"] == "none"
        assert client.patch(f"/api/clips/{cid}", json={"hook_choice": "auto"}).json()["hook"]["choice"] is None
        # mudar início/fim descarta o gancho (é avaliado de novo no próximo render)
        assert client.patch(f"/api/clips/{cid}", json={"start": s0 + 1}).json()["hook"] is None
        assert client.patch(f"/api/clips/{cid}", json={"hook_choice": 0}).status_code == 409


def test_generate_json_sends_schema_to_ollama(monkeypatch):
    """A avaliação de ganchos manda um JSON schema (saída estruturada): N itens, 7 notas inteiras 0–10."""
    import urllib.request

    sent = {}

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data))
        reply = {"a": [{"id": i, "n": [5 + i] * 7, "spoiler": False, "m": "ok"} for i in range(3)]}
        return Resp(json.dumps({"response": json.dumps(reply)}).encode())

    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = llm.evaluate_hooks("texto", [{"id": i, "text": f"frase {i}"} for i in range(3)], timeout=5)
    items = sent["format"]["properties"]["a"]
    assert items["minItems"] == items["maxItems"] == 3
    assert items["items"]["properties"]["n"]["minItems"] == 7
    assert sent["options"]["temperature"] == 0.2 and sent["options"]["num_predict"] > 0
    assert set(out) == {0, 1, 2}
