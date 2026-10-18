from app.pipeline import selection, transcribe
from app.pipeline.transcribe import _split_words


def make_transcript(sentences, gap=0.6, wps=2.8):
    segs, t = [], 1.0
    for s in sentences:
        dur = len(s.split()) / wps
        segs.append({"start": t, "end": t + dur, "text": s, "words": _split_words(s, t, t + dur)})
        t += dur + gap
    return {"engine": "test", "language": "pt", "duration": t, "segments": segs}


SENTS = [
    "Você sabia que o segredo do aprendizado é a repetição espaçada?",
    "Quando eu comecei a estudar eu não sabia nada sobre isso.",
    "Um dia eu descobri um método simples que mudou minha vida inteira.",
    "O método funciona assim: você revisa em intervalos cada vez maiores.",
    "Por isso a memória fica mais forte com o passar do tempo.",
    "E aí, tipo, isso que você falou antes também vale.",
    "Na minha opinião todo mundo deveria aprender isso na escola.",
    "A diferença entre quem aprende rápido e quem não aprende é a constância.",
    "Qual foi o maior erro que você cometeu no começo?",
    "O maior erro foi estudar tudo de uma vez, sem descanso nenhum.",
] * 3


def test_sentences_follow_punctuation_and_pauses():
    t = make_transcript(SENTS[:4])
    sents = selection.build_sentences(transcribe.all_words(t))
    assert len(sents) == 4
    assert sents[0].is_question and sents[0].complete


def test_long_unpunctuated_text_is_split():
    words = _split_words(" ".join(["palavra"] * 120), 0, 60)
    sents = selection.build_sentences(words, max_sentence_s=20)
    assert len(sents) >= 3
    assert all(s.end - s.start <= 20.5 for s in sents)


def test_candidates_respect_duration_and_sentence_boundaries():
    t = make_transcript(SENTS)
    sents = selection.build_sentences(transcribe.all_words(t))
    cands = selection.generate_candidates(sents, 15, 30)
    assert cands
    for c in cands:
        assert 15 <= c.duration <= 30
        assert c.sentences[-1].complete  # termina em frase completa


def test_selection_no_overlap_and_count():
    t = make_transcript(SENTS)
    chosen, alts = selection.find_clips(t, 4, 15, 30)
    assert len(chosen) == 4
    for a in chosen:
        for b in chosen:
            if a is not b:
                assert a.end <= b.start or b.end <= a.start
    assert all(0 <= c.score <= 100 for c in chosen + alts)
    assert chosen == sorted(chosen, key=lambda c: c.start)


def test_context_dependent_start_is_penalized():
    t = make_transcript(SENTS[:10])
    sents = selection.build_sentences(transcribe.all_words(t))
    indep = selection.Candidate(sents[0].start, sents[2].end, sents[0:3])
    dep = selection.Candidate(sents[4].start, sents[6].end, sents[4:7])
    selection.score_candidate(indep, None, (10, 40))
    selection.score_candidate(dep, None, (10, 40))
    assert indep.scores["independencia"] > dep.scores["independencia"]
    assert any("contexto" in r or "referência" in r for r in dep.reasons)
    assert indep.score > dep.score


def test_question_without_answer_penalized():
    t = make_transcript(SENTS[:10])
    sents = selection.build_sentences(transcribe.all_words(t))
    ends_q = selection.Candidate(sents[7].start, sents[8].end, sents[7:9])
    answered = selection.Candidate(sents[8].start, sents[9].end, sents[8:10])
    selection.score_candidate(ends_q, None, (5, 40))
    selection.score_candidate(answered, None, (5, 40))
    assert answered.scores["coerencia"] > ends_q.scores["coerencia"]
    assert answered.category == "Pergunta e resposta"


def test_short_material_relaxes_minimum():
    t = make_transcript(SENTS[:2])
    chosen, _ = selection.find_clips(t, 3, 30, 60)
    assert len(chosen) >= 1
