# Fase 2 — Ganchos inteligentes: relatório de validação

## O que mudou

| Antes (`enhance.pick_cold_open`) | Agora (`pipeline/hooks.py`) |
|---|---|
| Só frases de 1,5–4,5 s; frases longas quebradas ao meio | Frases de 1,5–6 s, orações de frases longas, duas frases curtas vizinhas e o começo de frases longas cortado só antes de uma nova parte da frase |
| Muletas ficavam no áudio do gancho | "Né", "aí", "tipo"… aparados no começo e no fim |
| Nota = ênfase + "!" + palavras do assunto (limite 0,6) | 7 critérios de 0 a 10: curiosidade, clareza, impacto, relevância, continuidade, fidelidade, payoff |
| Payoff: só 3 s antes e 1 s depois | Payoff: ≥ 8 s (ou 25% do corte, até 20 s) de contexto antes, ≥ 4 s de conclusão depois, nada dos últimos 20% do corte |
| Sem IA | Ollama avalia os mesmos candidatos com saída estruturada (JSON schema); nota = 60% IA + 40% regras |
| Calculado no render, sem registro | Calculado na análise, salvo em `clips.hook_json` com candidatos, notas, motivos e posição do payoff |
| Sem escolha manual | Editor do corte: escolher outro candidato, "Automático" ou "Sem gancho" |

A repetição intencional (gancho → desenvolvimento → payoff → conclusão) continua igual: o render nunca remove a
segunda ocorrência. Há um teste que confere a frase duas vezes nas legendas e a posição do payoff.

O que não mudou: filtro do FFmpeg, legendas, efeitos, motor Concat, seleção de cortes (`selection.py`), funcionamento
sem Ollama.

## Comparação nas histórias de teste

Episódios reais não puderam ser baixados neste ambiente (o YouTube pede login para servidores; o app não usa cookies
para contornar). A comparação usou **7 histórias escritas para o teste** (`backend/tests/data/hook_stories.json`), no
estilo de fala de podcast, com armadilhas: corte curto, frase que entrega o final e frase que muda de sentido com
"mas". A avaliação "melhor/boa/ruim" é minha, como editor; por isso a validação com os seus episódios (Fase 5) continua
necessária.

| História | Melhor gancho (esperado) | Antigo | Só regras | qwen2.5:7b (versão final) |
|---|---|---|---|---|
| Aeroporto | "o senhor vai ter que me acompanhar" | ruim (abertura da história) | boa ("Eu gelei…") | boa ("Eu gelei…")¹ |
| Falência | "trezentos mil… e zero na sexta" | ruim | **melhor** | **melhor** |
| Genro | "chegou de chinelo… pediu a minha filha" | ruim ("fiz churrasco") | ruim | ruim² |
| Pai | "a cadeira dele tava vazia" | **melhor** | **melhor** | **melhor** |
| Dívidas | "o banco prefere receber menos…" | **melhor** | boa | boa |
| Curto (6,7 s) | sem gancho | sem gancho | sem gancho | sem gancho |
| Spoiler | não entregar o final | boa | boa | boa |

¹ Primeira chamada depois de reiniciar o Ollama: o modelo levou ~5 min para carregar, passou do limite e o app usou as
regras (comportamento esperado).
² Instável: numa versão anterior do prompt o mesmo modelo escolheu a frase certa (nota 9,3); em duas outras, "fiz
churrasco". O julgamento do modelo de 7B muda com pequenas diferenças no texto enviado. A escolha manual no editor
resolve esses casos.

Resumo: o seletor antigo escolheu frases de abertura da história (sem tensão) em 3 de 6 casos; o novo, em 1 de 6, e
nunca escolheu a revelação final. Com versões anteriores do prompt, `qwen2.5:3b` e `llama3.2:3b` também foram testados
(tabela de tempos abaixo).

## Ollama real (instalado neste ambiente)

Servidor de teste: 4 núcleos de CPU, 15 GB de RAM, **sem GPU**.

| Modelo | Tempo por corte | Memória | Observação |
|---|---|---|---|
| qwen2.5:7b | 48–100 s (1ª chamada até ~5 min, carregando o modelo) | 5,2 GB | Melhores escolhas; recomendado |
| qwen2.5:3b | 31–56 s | ~2,5 GB | Bom; opção para PCs com menos memória |
| llama3.2:3b | 34–58 s | ~2,5 GB | Sem saída estruturada, deu nota 2 a todos; com ela, escolhas aceitáveis, mas recusou um gancho bom |
| Só regras | < 0,02 s | — | Usado quando a IA está desligada, falha ou passa do limite |

Fluxo completo pela API com `qwen2.5:7b` (análise → gancho → render de 1 corte): 164 s, gancho avaliado em 37,8 s,
pico de memória do Python 244 MB.

Problemas encontrados e corrigidos durante os testes com o modelo real:
- O modelo copiava o exemplo do prompt (quantidade de itens e motivos). Corrigido com saída estruturada (JSON schema
  com exatamente N itens e 7 notas inteiras de 0 a 10).
- Respostas incompletas ou com a mesma nota para todos agora são descartadas; vale a heurística.
- Os dois modelos qwen escolhiam a revelação final ("o senhor tem um homônimo…") sem marcá-la como spoiler.
  Corrigido com a regra fixa dos últimos 20% do corte e pedindo ao modelo que escreva primeiro qual é o desfecho.
- Cortes de frases longas paravam no meio de expressões ("na frente de todo", "com vinte"). Agora o corte só acontece
  antes de uma palavra que abre outra parte da frase.

## Como validar com os seus episódios

Na pasta `backend`, com o ambiente do ClipFlow ativo:

```
python -m app.tools.hooks_compare            # lista os projetos com transcrição
python -m app.tools.hooks_compare <projeto>  # antigo × novo, com notas, motivo da IA e tempo
```

O comando só lê (não altera cortes) e grava um relatório JSON em `ClipFlowStudio/logs/`.

## Validação com episódios reais (2 transcrições enviadas pelo usuário)

Dois episódios de 2 h 24 min e 2 h 40 min, transcritos pelo Whisper `small` na máquina do usuário. Para cada um, o
app escolheu 5 cortes (30–60 s) e cada corte passou pelo gancho antigo, pelas regras novas e pelo `qwen2.5:7b`.
Avaliação editorial minha, lendo o texto completo de cada corte:

| Corte | Antigo | Novo (regras = IA nos 10 casos) | Veredito |
|---|---|---|---|
| Ep.1 · 1 | sem gancho | "As pessoas que fazem você dá certo…" | novo fraco (transcrição truncada) |
| Ep.1 · 2 | trecho sem pontuação | trecho sem pontuação ("Obriga que a gente estava no carro…") | os dois ruins |
| Ep.1 · 3 | "Meu irmão João Carlos é maravilhoso…" | "Por que sabe que a família não é que é do sangue?" | **novo melhor** |
| Ep.1 · 4 | "tira uma foto comigo…" | "Tira uma foto comigo…" (havia "comecei a passar mal… a polícia veio") | os dois fracos |
| Ep.1 · 5 | "eu já fui corno também…" | igual | os dois bons |
| Ep.2 · 1 | "a gente tem que sofrer um grande trauma" | "a gente só evolui quando absorve o trauma…" | os dois bons |
| Ep.2 · 2 | "aquela mesa lá ficou pequena" | "Você lembra que você levou a gente lá?" | os dois ruins (o corte em si pula de assunto) |
| Ep.2 · 3 | "Fico vendo coisas de curiosidade e E.T." | "O cara acredita em E.T.… Eu acredito." | **novo melhor** |
| Ep.2 · 4 | "Imagina que bosta, Gabriel…" | "O Neymar tem quantos filhos? 1, registrado, 3 não, 7, 7." | **novo melhor** |
| Ep.2 · 5 | "se ele não quisesse ser gordo…" | "Tu tomou o monjaro?" | empate |

Resultado: novo melhor em 3, empate em 5 (2 bons, 3 fracos/ruins nos dois), pior em nenhum; o antigo não tinha gancho
em 1 corte e o novo deu um fraco.

**O que os episódios reais mostraram (e as histórias de teste não):**

1. **A IA não mudou nenhuma escolha.** Nos 9 cortes em que respondeu, o `qwen2.5:7b` concordou com a ordem das regras;
   os motivos que ele escreve são genéricos ("desafia a curiosidade… mas revela o desfecho" para quase todos). Custo:
   ~70 s por corte nesta CPU, sem ganho medido nesta amostra. Na 1ª chamada após iniciar o Ollama o modelo não
   carregou em 5 min (limite do próprio Ollama) e o app usou as regras, como previsto.
2. **A transcrição limita o gancho.** O Whisper `small` gera trechos longos sem pontuação e palavras erradas
   ("obriga", "coxtei", "devolador"); o gancho herda isso. Modelo `medium` (ou `large-v3-turbo` com GPU) deve ajudar
   mais do que qualquer ajuste de gancho.
3. **Problemas de seleção (Fase 3):** os 5 cortes de cada episódio caíram todos nos primeiros 46 min (os candidatos
   cobrem o episódio inteiro; a escolha final só pega as 5 maiores notas); 66 de 70 candidatos foram classificados
   como "Pergunta e resposta" (qualquer "?" na conversa conta); os cortes ficaram em 30–37 s, encostados no mínimo; e
   um deles (Ep.2 · 2) mistura três assuntos.
