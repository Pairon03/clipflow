"""Descrições e textos da caixa: frases que fazem sentido sozinhas, contexto e validação da IA local."""
import pytest

from app.pipeline import llm, metadata, overlay, phrases

NETO = ("E aí, né, cara, eu falo isso pra todo mundo. O Neymar ele tinha tudo pra ser o melhor do mundo, tá ligado? "
        "Mas aí ele escolheu a balada, escolheu a farra, né. Isso aí eu falo na cara dele. Eu acho que o Neymar "
        "desperdiçou a carreira dele. Tipo assim, talento ele tem mais que o Messi, mais que o Cristiano. Só que "
        "talento sem disciplina não vale nada. E aí o pessoal fica bravo comigo, né, mas é a verdade.")
ANA = ("Então, eu tinha dezessete anos quando eu saí de casa, né. Aí eu fui pra São Paulo sem conhecer ninguém. "
       "Eu dormi na rodoviária duas noites, cara. Ninguém sabe disso. E aí eu consegui um emprego de garçonete.")
DIVIDAS = ("Pergunta que eu mais recebo é essa: como que eu saio das dívidas? E a resposta é simples, mas não é fácil. "
           "O primeiro passo é parar de fazer dívida nova, né. Aí o segundo passo é renegociar.")


@pytest.mark.parametrize("raw,clean", [
    ("E aí, né, cara, eu falo isso pra todo mundo.", "Eu falo isso pra todo mundo."),
    ("O Neymar ele tinha tudo pra ser o melhor do mundo, tá ligado?", "O Neymar tinha tudo pra ser o melhor do mundo."),
    ("Mas aí ele escolheu a balada, escolheu a farra, né.", "Ele escolheu a balada, escolheu a farra."),
    ("Eu eu nunca, tipo, desisti.", "Eu nunca, desisti."),
])
def test_clean_removes_fillers(raw, clean):
    assert phrases.clean(raw) == clean


def test_best_quote_prefers_standalone_sentence():
    q = phrases.best_quote(NETO, ["neymar", "talento"], max_chars=80)
    assert q in ("Eu acho que o Neymar desperdiçou a carreira dele.", "Talento sem disciplina não vale nada.")
    # frases que dependem do contexto ou só têm muleta nunca vencem
    for bad in ("Isso aí eu falo na cara dele", "Eu falo isso pra todo mundo", "Ele escolheu a balada"):
        assert phrases.score(phrases.clean(bad + "."), ["neymar"]) < phrases.score(q, ["neymar"])
    assert phrases.best_quote("É. Tá. Né, cara, então aí.", []) is None


def test_questions_and_topic():
    assert phrases.best_question(NETO) is None                     # "tá ligado?" não é pergunta
    assert phrases.best_question(DIVIDAS) == "Como que eu saio das dívidas?"
    assert phrases.topic(NETO, exclude=("Craque Neto", "Podpah")) == "Neymar"
    assert phrases.topic(ANA, exclude=("Ana Paula",)) == "São Paulo"
    assert phrases.topic(DIVIDAS, source_title="Como sair das dívidas | Primo Rico") == "dívidas"
    assert not phrases.hashtag_ok("escolheu") and not phrases.hashtag_ok("receber") and phrases.hashtag_ok("talento")


def test_parse_source_only_accepts_names():
    assert metadata.parse_source("CRAQUE NETO - Podpah #1093") == ("Craque Neto", "Podpah")
    assert metadata.parse_source("Flow Podcast #300 - Ana Paula") == ("Ana Paula", "Flow Podcast")
    assert metadata.parse_source("Como sair das dívidas | Primo Rico") == ("Primo Rico", None)


def test_description_is_built_and_specific():
    m = metadata.heuristic(NETO, "CRAQUE NETO - Podpah #1093", "Opinião")
    d = m["description"].split("\n\n")
    assert "Neymar" in d[0]                                         # gancho fala do assunto
    assert any(line == "No Podpah, Craque Neto fala sobre Neymar." for line in d)
    assert "né" not in m["description"].split("#")[0] and "tá ligado" not in m["description"]
    assert "#escolheu" not in m["hashtags"] and "#neymar" in m["hashtags"]
    caixa = overlay.card_text("caixa", m["card"])
    assert caixa.startswith("Craque Neto deu a real:\n") and "Neymar" in caixa or "disciplina" in caixa


def test_card_falls_back_to_topic_instead_of_random_sentence():
    text = "Aí ele foi lá e. Isso aí. Né, cara, e aí, tipo, o Flamengo. O Flamengo, né, aí."
    m = metadata.heuristic(text, "ZICO - Podpah #500", "História")
    assert m["card"]["quote"] is None
    assert overlay.card_text("caixa", m["card"]) == "Zico sobre Flamengo"
    assert overlay.card_text("citacao", m["card"]) is None         # sem frase boa, sem citação solta


def test_in_transcript_tolerates_removed_fillers():
    assert phrases.in_transcript("Talento sem disciplina não vale nada", NETO)
    assert phrases.in_transcript("o Neymar desperdiçou a carreira", NETO)
    assert not phrases.in_transcript("Neymar é o melhor jogador da história", NETO)


def test_ollama_parts_are_validated(monkeypatch):
    good = {"titulos": ["Craque Neto: Neymar desperdiçou a carreira"], "gancho": "🔥 Craque Neto não aliviou pro Neymar",
            "contexto": "No Podpah, ele diz que faltou disciplina ao Neymar.", "chamada": "Você concorda? 👇",
            "caixa": {"chamada": "Craque Neto sobre o Neymar", "frase": "Talento sem disciplina não vale nada"}}
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "metadata", lambda text, title: good)
    m = metadata.generate(NETO, "CRAQUE NETO - Podpah #1093", "Opinião")
    assert m["engine"] == "ollama+heuristica"
    assert m["description"].startswith("🔥 Craque Neto não aliviou pro Neymar\n\nNo Podpah, ele diz")
    assert "“Talento sem disciplina não vale nada”" in m["description"] and "Você concorda? 👇" in m["description"]
    assert overlay.card_text("caixa", m["card"]) == "Craque Neto sobre o Neymar:\nTalento sem disciplina não vale nada"

    invented = good | {"caixa": {"chamada": "Craque Neto:", "frase": "Neymar é o pior jogador da história"},
                       "contexto": "Ele disse “Neymar é o pior da história”."}
    monkeypatch.setattr(llm, "metadata", lambda text, title: invented)
    m = metadata.generate(NETO, "CRAQUE NETO - Podpah #1093", "Opinião")
    assert "pior" not in overlay.card_text("caixa", m["card"])       # frase inventada: fica a escolhida pelo app
    assert "pior da história" not in m["description"]                # contexto com citação falsa descartado
