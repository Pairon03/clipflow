# Status das funcionalidades

Legenda: ✅ implementado e testado · 🟡 implementado, verificação parcial · 🧪 testado apenas com simulação ·
⏳ pendente (fase futura)

Ambiente de testes: Linux, Python 3.13, FFmpeg 6.1 (libass), Chromium headless. **163 testes automatizados:
161 passam, 2 são pulados** (Whisper e Concat real — ver abaixo). O fluxo completo também foi percorrido pela interface real no
navegador (upload → revisão → render → biblioteca), sem erros no console.

## Fase 1 — MVP

| Funcionalidade | Status | Observações |
|---|---|---|
| Upload de vídeo (MP4, MOV, MKV, WEBM…) com progresso real | ✅ | streaming direto para o disco, limite de tamanho, validação por FFprobe |
| Informações do arquivo (nome, tamanho, duração, resolução) | ✅ | |
| Validação de URL do YouTube | ✅ | 19 casos testados (válidos, playlists, hosts falsos, injeção) |
| Metadados do YouTube (título, canal, miniatura, duração) | 🧪 | testado com yt-dlp simulado: **este sandbox bloqueia youtube.com**. Código usa a API oficial do yt-dlp |
| Download autorizado via yt-dlp | 🧪 | idem. Sem cookies, sem contornar restrições. O YouTube muda com frequência: mantenha o yt-dlp atualizado (`pip install -U yt-dlp`); versões recentes podem exigir o runtime [Deno](https://deno.com) para alguns vídeos |
| Recusa de vídeos privados/idade/membros/ao vivo/DRM | ✅ | regras testadas com metadados simulados |
| Confirmação e registro de direitos de uso | ✅ | base legal + documentação + data, gravados no banco e em `project.json` |
| Transcrição faster-whisper (pt-BR, timestamps por palavra, VAD) | 🟡 | **código pronto, mas não executado aqui**: o download do modelo do Hugging Face é bloqueado neste sandbox (HTTP 403). O teste roda automaticamente quando o modelo estiver em cache. Precisa ser validado na sua máquina |
| Importação de legenda SRT/VTT (alternativa ao Whisper) | ✅ | tempos por palavra estimados proporcionalmente |
| Exportação SRT (transcrição completa e por Short) | ✅ | |
| Seleção inicial de cortes | ✅ | |
| Legendas animadas | ✅ | |
| Exportação vertical 1080×1920 H.264/AAC | ✅ | verificada por FFprobe + decodificação completa |
| Download individual e ZIP | ✅ | ZIP inclui SRT e arquivo com títulos/descrições |

## Fase 2 — Qualidade premium

| Funcionalidade | Status | Observações |
|---|---|---|
| Pontuação em 7 critérios + motivos | ✅ | clareza, independência de contexto, interesse, retenção, áudio, coerência, cortes suaves |
| Cortes sempre em frases completas, penalização de dependência de contexto | ✅ | |
| Bônus por estilo (motivacional, educativo…) | ✅ | |
| Reavaliação com IA local (Ollama) | 🧪 | testado com servidor Ollama simulado; fallback automático se indisponível |
| Legendas por palavra (destaque da palavra falada) | ✅ | sincronia verificada medindo fala no áudio final no início de cada bloco |
| Estilos Classic, Neon, Minimal, Impact + cores/tamanho/posição | ✅ | cores e tamanho via API (`caption_colors`); a interface ainda não expõe o seletor de cores |
| Área de segurança (UI do Shorts) | ✅ | legenda a 30% da base; no layout dividido, centralizada |
| Detecção de rostos (MediaPipe BlazeFace + Haar) | ✅ | testado com fotos reais em vídeo sintético |
| Rastreamento + câmera suave (zona morta, limite de velocidade) | ✅ | |
| Layout dividido para 2 pessoas | ✅ | escolhido automaticamente quando os rostos não cabem num corte 9:16 |
| Quadro inteiro com fundo desfocado / central / manual | ✅ | |
| Alternar para quem está falando | 🟡 | **experimental**: usa movimento da região da boca. Renderiza corretamente, mas a precisão da troca não foi medida com podcasts reais |
| Revisão: prévia, ajuste de início/fim, troca por alternativa, correção de legenda | ✅ | correção mantém a sincronização (alinhamento por diff) |
| Remoção de pausas longas | ✅ | |
| Gancho com payoff: 7 critérios, regras de payoff, IA local, escolha manual | ✅ | testado com Ollama real (qwen2.5:7b, qwen2.5:3b, llama3.2:3b) em histórias escritas para o teste; ver docs/FASE2_GANCHOS.md. Falta validar com episódios reais |
| Ritmo TikTok (corta respirações) e aceleração 1.1x/1.2x | ✅ | corte em uma passada (select/aselect) alinhado aos quadros; sincronia de áudio e vídeo verificada |
| Gancho de abertura (fala forte antes do início) | ✅ | só quando há frase curta, completa e de destaque; testado com vídeo sintético |
| Títulos tweet / caixa / citação / variar | ✅ | PNG desenhado com Pillow e sobreposto pelo FFmpeg; quadros renderizados conferidos visualmente, inclusive no layout dividido |
| Identidade do canal (nome, @, logo) no cartão de tweet | ✅ | upload validado, recorte quadrado de 256 px |
| Título "faixa branca" (manchete no topo, vídeo abaixo) | ✅ | quadros conferidos nos layouts seguir e dividido |
| Legenda "Amarela" (itálico, nomes próprios em vermelho) | ✅ | fonte Poppins ExtraBold Italic (OFL); nomes = inicial maiúscula fora do começo da frase |
| Título no topo ou no meio da tela | ✅ | centralizado pela altura real do cartão; quadro renderizado conferido |
| Transição depois do gancho (zoom, flash, escurecer) | ✅ | quadros renderizados conferidos |
| Zoom de ênfase no motor FFmpeg | ✅ | scale por quadro + crop; no máximo um a cada ~8 s |
| Efeitos sonoros (whoosh, pop) | ✅ | teste mede o whoosh no instante da transição e a fala idêntica fora dos efeitos |
| Palavrões silenciados / bipe e mascarados no texto | ✅ | teste mede silêncio total e o bipe em 1 kHz; depende da transcrição reconhecer a palavra |
| Filtros de cor (Vivo, Quente, Frio, Cinema, Vintage, P&B) com prévia | ✅ | filtros do FFmpeg (eq, colorbalance, curves, vignette); prévia num quadro do próprio vídeo |
| Normalização de áudio (loudnorm −14 LUFS) e fades discretos | ✅ | |
| Rostos pequenos em planos muito abertos | 🟡 | MediaPipe short-range pode falhar; o Haar assume. Se nada for detectado, usa corte central |

## Fase 3 — Automação

| Funcionalidade | Status | Observações |
|---|---|---|
| Fila persistente (SQLite) com limite de concorrência | ✅ | teste com 3 projetos em lote, limite 1 respeitado |
| Progresso real (FFmpeg `-progress`, segmentos do Whisper, download) | ✅ | |
| Cancelamento (encerra o FFmpeg imediatamente) | ✅ | |
| Tentativas controladas (erros recuperáveis) | ✅ | erros fatais não são repetidos |
| Recuperação após reinício do servidor | ✅ | tarefas "running" voltam para a fila |
| Prevenção de processamento duplicado | ✅ | por ID do YouTube ou impressão digital do arquivo |
| Dashboard (contagens, consumo, armazenamento) | ✅ | |
| Histórico e logs por projeto | ✅ | |
| Títulos (até 3), descrição, hashtags, palavras-chave | ✅ | heurística usa só frases reais da fala; IA local validada |
| Biblioteca com busca, filtro, seleção, ZIP e exclusão | ✅ | |
| Relatórios de processamento exportáveis | ⏳ | hoje: dashboard + log por projeto |

## Integração com o editor Concat (opcional)

| Funcionalidade | Status | Observações |
|---|---|---|
| Detecção do executável e validação do caminho | ✅ | só aceita executáveis com nome `concat*` |
| Cliente MCP (stdio) com tempo limite e erros legíveis | ✅ | testado com servidor falso e com o `concat-mcp` real (v0.2.7, compilado do código enviado) |
| "Editar no Concat": vídeo sem legenda + projeto 1080×1920 + legendas editáveis | ✅ | o projeto criado foi reaberto e **exportado pelo próprio Concat** (H.264/AAC 1080×1920) com as legendas |
| "Abrir": abre o projeto na janela do Concat | 🟡 | usa `concat --project <pasta>`. **Não testado com a janela**: aqui só existe o binário sem interface gráfica |
| Motor "Edição com IA (Concat)": zoom de ênfase | ✅ | keyframes de escala conferidos no projeto do Concat e visíveis no MP4 exportado |
| Texto de gancho nos primeiros segundos | ✅ | posição e largura ajustadas depois de olhar o quadro renderizado |
| Exportação pelo Concat, com progresso e cancelamento | ✅ | testado com o `concat-mcp` real; volta para o FFmpeg se o Concat falhar |
| Escolha dos zooms pela IA local (Ollama) | ⏳ | hoje a escolha é heurística, pela fala |
| Correção de cor por estilo, transições, estabilização | ⏳ | próximos passos com as ferramentas do Concat |
| Instalador do Concat para Windows | ⏳ | você instala o Concat separadamente (download oficial) |

## Fase 4 — Expansão (pendente)

| Funcionalidade | Status |
|---|---|
| Integração com YouTube Data/Analytics API (OAuth) | ⏳ |
| Publicação automática (com revisão prévia) | ⏳ |
| Modelos de edição personalizados salvos | ⏳ |
| Multiusuário / SaaS | ⏳ |
| Diarização de locutores (pyannote) para "quem fala" mais preciso | ⏳ |

## Medições neste ambiente (CPU de 4 núcleos, sem GPU)

- Render de um Short de ~20 s (layout dividido, legendas, loudnorm, verificação): **~6 s**.
- Pico de memória: **~260 MB** no processo Python, **~480 MB** no FFmpeg.
- Os vídeos de teste são sintéticos (fundo fixo), então o tamanho por minuto medido (2,3 MB) é bem menor que o de
  um podcast real; espere algo como 15–40 MB por minuto com CRF 20.
- Tempo de transcrição com Whisper: **não medido** (modelo indisponível no sandbox).

## Limitações conhecidas

- A pontuação editorial é heurística (marcadores de linguagem em português, pausas, confiança da transcrição,
  qualidade de áudio). Ela evita cortes no meio de frases e trechos dependentes de contexto, mas não "entende"
  o conteúdo como um editor humano — por isso a revisão é recomendada. Com o Ollama a avaliação melhora.
- Legendas importadas de SRT têm tempo por palavra estimado (o destaque pode adiantar/atrasar um pouco dentro
  de cada bloco). Com o Whisper os tempos vêm do alinhamento do próprio modelo.
- A prévia na revisão mostra o vídeo original com recorte central aproximado (o enquadramento final é calculado
  no render).
