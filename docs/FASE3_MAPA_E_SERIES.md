# Fase 3 — Mapa do episódio, cortes espalhados e séries (Parte 1, 2…)

## O problema medido

Nas duas transcrições reais (2 h 24 min e 2 h 40 min), os 5 cortes caíam todos nos primeiros 13–45 minutos.
A causa **não** era a IA "não entender" o fim do episódio:

- os 50 melhores trechos estavam espalhados pelos quatro quartos do episódio (40/10/24/26% e 12/30/28/30%);
- mas o bônus de estilo (+4) estourava o teto de 100: **59 e 151 trechos empatavam na nota máxima**, e no
  empate ganhava quem foi gerado primeiro (ordem cronológica);
- a nota mal diferenciava os trechos (quase tudo entre 80 e 91) e 58% dos candidatos eram "Pergunta e resposta"
  só por terem um "?" no meio;
- a nota era local: janelas de 30–60 s soltas, sem saber onde uma história começa e termina.

## Passo 1 — correções (pipeline/selection.py)

- Nota sem arredondamento e com escala que não estoura: o bônus de estilo completa 100 sem empatar.
- Desempate por interesse e retenção, nunca pela posição no vídeo.
- Cortes espalhados: no máximo `ceil(quantidade × 20 min / duração)` por trecho de 20 min na 1ª passada; se
  faltar corte, uma 2ª passada completa sem esse limite.
- "Pergunta e resposta" exige pergunta curta na 1ª metade do corte seguida de resposta (≥ 8 s ou 40% do corte).

## Passo 2 — mapa do episódio (pipeline/episode.py)

1. **Blocos de assunto/história** (40 s a 6 min): fronteiras entre frases ganham pontos por pausa longa, queda
   do vocabulário em comum entre os 45 s antes e depois (mudança de assunto) e frases que abrem história ou
   assunto ("deixa eu te contar", "uma vez", "mudando de assunto"). Blocos longos são divididos na melhor
   fronteira interna.
2. **Nota do bloco inteiro** pelas regras: narração em 1ª pessoa no passado ("fui", "cheguei", "falei"…),
   marcadores de história/emoção/opinião, números, pergunta com resposta longa, densidade de fala e energia da
   voz. Propaganda ("cupom", "link na descrição", "se inscreve"…) e abertura/encerramento ("boa noite", "sejam
   bem-vindos", "até a próxima") derrubam a nota. A nota final é a **posição do bloco no episódio** (0–100),
   então usa a escala inteira.
3. **IA local (opcional)**: os 6 melhores blocos (ajustável em Configurações, 0 desliga) vão inteiros para o
   Ollama, que devolve título, resumo de uma linha, nota 0–100 pelo "teste dos 2 segundos", se tem desfecho e se
   se entende sozinho. Nota final do bloco = metade regras, metade IA.
4. **Seleção**: nota do corte = 45% nota local da janela + 55% nota do bloco; +5 se o corte começa onde o
   assunto começa; −12 se atravessa dois assuntos; −40 em propaganda/abertura. Na 1ª passada, **um corte por
   assunto**.
5. O mapa fica salvo (`transcripts/<id>/episode_map.json`) e é reaproveitado ao refazer a seleção.

Na página do projeto, **Mapa do episódio** mostra a linha do tempo colorida pela nota e a lista de assuntos com
título, resumo, nota e os botões **Corte** (melhor janela daquele assunto) e **Série**.

## Passo 3 — séries (pipeline/series.py)

- **Nem toda história vira série.** Só quando: bloco de história com nota ≥ 75, mais longo que 1,25× a duração
  máxima, divisível em 2 a 4 partes com bons pontos de suspense (média ≥ 0,5) e, com a IA ligada, se a IA disse que
  a história tem desfecho e deu nota ≥ 65. No máximo 2 séries por episódio. As outras histórias longas ganham o
  botão **Série** no mapa, para você decidir.
- Os cortes da série substituem os cortes comuns que estavam dentro da mesma história.
- Pontos de corte só em fim de frase, escolhidos por programação dinâmica: cada parte dentro da duração pedida,
  perto do alvo, terminando no melhor ponto de suspense (pergunta, "aí ele olhou pra mim…", pausa antes de "só
  que", "quando eu vi"). Cada parte nova custa caro, então o suspense decide **onde** cortar, não faz cortar mais.
- Da Parte 2 em diante, a última frase da parte anterior abre o vídeo como retomada (fala real; nada inventado).
  Essas partes não têm gancho (cold open); a Parte 1 pode ter.
- No vídeo, tarja vermelha **PARTE 2/3** logo abaixo do título (ou no topo, sem título).
- Títulos e descrição iguais para todas as partes (gerados da história inteira), com "(Parte 2/3)" e a linha
  "Parte 2 de 3. A continuação está no próximo vídeo do perfil 👇" / "Parte final".
- Na publicação no YouTube, as partes ficam juntas e em ordem (horários seguidos), e o app avisa se faltar parte.
- Opção "Séries (Parte 1, 2…) nas melhores histórias" em Criar Shorts e em Preferências (ligada por padrão).

## Ideias do OpenShorts (MIT) aproveitadas

O OpenShorts (clone open source do Opus Clip) foi estudado: licença MIT no núcleo (a pasta `cloud/` tem licença
comercial e não foi usada). Nenhum código foi copiado; as ideias adaptadas:

- visão do episódio inteiro antes de cortar e nota usando a escala inteira ("teste dos 2 segundos", corte que
  se sustenta sozinho, diversidade entre cortes) — no mapa do episódio e no prompt da IA;
- **enquadramento** (pipeline/framing.py):
  - detecção de troca de câmera pela diferença entre quadros: a câmera reposiciona na hora em vez de fazer
    panorâmica lenta; se o rosto principal some depois da troca, segue o maior rosto da cena nova;
  - salto grande do alvo só é seguido depois de confirmado em 3 amostras (erro de detecção não balança a câmera);
  - "quem está falando" compara o movimento da boca de cada pessoa na escala dela mesma (percentis 20–80), com
    margem mínima e confirmação; antes, quem estava mais perto/iluminado "falava" sempre mais.

O que o OpenShorts faz e **não** foi trazido: tudo o que depende do Gemini pago (escolha de layout por visão,
detecção de legenda queimada, ganchos por visão) e a parte comercial. O OpenShorts não tem séries/continuações.

## Resultados nas transcrições reais (só regras)

| | Antes | Depois |
|---|---|---|
| Posição dos 5 cortes, ep. 1 (144 min) | 13,8 – 34,0 min | 17,4 – 118,5 min |
| Posição dos 5 cortes, ep. 2 (160 min) | 26,9 – 45,5 min | 39,4 – 133,2 min |
| Candidatos "Pergunta e resposta" | 58% / 69% | 23% / 22% |
| Trechos empatados na nota máxima | 59 / 151 | 0 |
| Mapa do episódio | — | 84 e 93 assuntos em 2–4 s |
| Séries automáticas (ep. 2) | — | 2 (2 e 3 partes) |

## Teste com a IA local real (qwen2.5:7b, CPU de 4 núcleos, sem GPU)

Os 6 melhores assuntos do episódio 2 avaliados pelo Ollama: **578 s no total (~96 s por assunto)**, já contando o
carregamento do modelo. Resultado:

| Assunto (min) | Regras | IA | Desfecho? | Título da IA |
|---|---|---|---|---|
| 111,0 | 97 | 82 | sim | Reflexo e experiências |
| 133,2 | 98 | 78 | sim | Recuperação e amizade |
| 39,4 | 100 | 55 | não | Auxílio emergencial e opiniões |
| 45,2 | 99 | 55 | não | Gordura e Metabolismo |
| 46,3 | 96 | 55 | não | Treino noturno e dificuldade de dormir |
| 138,2 | 95 | 55 | não | Conversa sobre amizade |

- Os títulos e resumos da IA são bem melhores que os das regras ("Senti", "BGS").
- A IA separou o que as regras empatavam: histórias com desfecho subiram, conversas sem conclusão desceram.
- A série automática do bloco "Auxílio" (criada só com as regras) **não** é criada com a IA ligada, porque a IA
  disse que a história não tem desfecho — o comportamento pedido: só vira série o que vale a pena.
- O modelo de 7B tende a repetir a mesma nota (55) para vários blocos medianos; por isso a nota final é metade
  regras, metade IA.
- Em CPU, cada assunto leva ~1,5 min: o padrão é avaliar 6 (≈ 9 min a mais por episódio). Com placa de vídeo é
  bem mais rápido. Em Configurações, "Assuntos do episódio avaliados pela IA" = 0 desliga.
