# ClipFlow Studio

Plataforma local para transformar podcasts, entrevistas e vídeos longos em **YouTube Shorts, Reels e TikToks**:
transcrição → seleção dos melhores momentos → enquadramento vertical com rastreamento de rostos →
legendas animadas palavra a palavra → renderização 1080×1920 (H.264/AAC) → títulos, descrições e hashtags.

Tudo roda **no seu computador**, sem APIs pagas (custo mensal: R$ 0). A IA local via Ollama é opcional.

> **Fase atual: 1 (MVP funcional) concluída, com boa parte da Fase 2 e 3.**
> Veja o que está pronto, o que é simulado nos testes e o que falta em [docs/STATUS.md](docs/STATUS.md).

---

## Instalação no Windows

### 1. Pré-requisitos (uma vez só)

| Programa | Como instalar | Para quê |
|---|---|---|
| **Python 3.13** (ou 3.12) | [python.org/downloads/windows](https://www.python.org/downloads/windows/). **Não use 3.14/3.15**: a transcrição ainda não tem pacotes para elas. Pode ficar instalado junto com outras versões | backend e IA |
| **Node.js LTS** | [nodejs.org](https://nodejs.org) | compilar a interface (só na instalação) |
| **FFmpeg (build "full")** | no PowerShell: `winget install Gyan.FFmpeg` | corte, render e legendas |

Sem `winget`? Baixe o FFmpeg em [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) (versão *full*)
e copie `ffmpeg.exe` e `ffprobe.exe` para uma pasta `bin\` dentro do projeto.

### 2. Instalar o ClipFlow Studio

Dê dois cliques em **`setup-windows.bat`**. Ele cria o ambiente Python (`.venv`), instala as dependências,
compila a interface e cria o `config.toml`. Leva alguns minutos e baixa ~1 GB.

### 3. Abrir

Dê dois cliques em **`start-windows.bat`**. O navegador abre em <http://127.0.0.1:8000>.

Na **primeira transcrição**, o modelo Whisper escolhido é baixado automaticamente do Hugging Face
(`small` ≈ 480 MB). Depois disso funciona offline.

### Linux / macOS

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)
cp config.example.toml config.toml
./start.sh
```

---

## Como usar

1. **Criar Shorts** → cole o link de um vídeo do YouTube autorizado (clique em *Buscar vídeo* para ver título,
   miniatura e duração) **ou** arraste um arquivo de vídeo.
2. *(Opcional)* Envie a legenda `.srt/.vtt` se já tiver — pula a transcrição.
3. Escolha a base legal de uso, documente a autorização e confirme os direitos.
4. Defina quantidade (3/5/10/personalizada), duração (15–30s, 30–60s, 60–90s, personalizada até 180s),
   estilo, legenda e enquadramento.
5. Clique em **Gerar Shorts**. Acompanhe o progresso real na página do projeto (pode fechar a aba).
6. Marque *"Revisar cortes antes de renderizar"* se quiser ouvir as prévias, ajustar início/fim, corrigir a
   legenda, trocar por alternativas ou mudar o enquadramento antes de renderizar.
7. Baixe cada Short (MP4 + SRT) ou tudo em ZIP — o ZIP inclui um arquivo com os títulos e descrições sugeridos.

### Dicas para computadores modestos

Em **Configurações**: modelo Whisper `base` (ou `tiny`), 1 tarefa simultânea, preset `veryfast` e, se
necessário, desative o rastreamento de rostos. Ou envie a legenda `.srt` e pule o Whisper.

| Computador | Modelo sugerido | Tempo aproximado de transcrição* |
|---|---|---|
| 8 GB RAM, CPU de 4 núcleos | `base` | ~0,3–0,5× a duração do vídeo |
| 16 GB RAM, CPU de 6–8 núcleos | `small` (padrão) | ~0,5–1× a duração |
| GPU NVIDIA (CUDA) | `large-v3-turbo` | bem abaixo de 0,2× |

\*Estimativas de referência do faster-whisper em int8; **não medidas neste projeto** (veja STATUS.md).

### Placa de vídeo NVIDIA (opcional, transcrição bem mais rápida)

No modo **Automático**, o ClipFlow tenta usar a GPU NVIDIA. Se as bibliotecas CUDA não estiverem instaladas,
ele volta sozinho para o processador (CPU) e registra o motivo no log. Para ativar a GPU, rode na pasta do
ClipFlow:

```
.venv\Scripts\pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

Depois reabra o `start-windows.bat`. Suporte à GPU ainda **não testado** em máquina real; se der erro, volte o
Dispositivo para CPU em Configurações.

### IA local opcional (Ollama)

1. Instale o [Ollama](https://ollama.com) e rode `ollama pull llama3.2:3b` (≈2 GB; precisa de ~4 GB de RAM livre).
2. Em **Configurações**, ative *Usar Ollama*.

Com o Ollama ativo, os 15 melhores candidatos são reavaliados pela IA (30% da nota final) e os títulos/descrições
são sugeridos por ela — sempre validados (citações que não existem na fala são descartadas). Sem o Ollama, o motor
heurístico local funciona normalmente.

### Editor Concat opcional (ajustes finos, estilo CapCut)

O [Concat](https://github.com/jub0t/Concat) é um editor de vídeo gratuito e open source. Com ele instalado
([download](https://concatenate.pages.dev/#download)), cada Short ganha o botão **Editar no Concat**:

1. O ClipFlow renderiza uma versão do corte **sem legenda queimada** (`exports/<projeto>/<corte>_clean.mp4`).
2. Cria um projeto do Concat em 1080×1920 (`ClipFlowStudio/concat/<projeto>/<corte>/`) com esse vídeo e as legendas
   como **textos editáveis**, um bloco por frase curta.
3. **Abrir** abre o projeto na janela do Concat. Lá você ajusta textos, efeitos e transições e exporta.

O ClipFlow detecta o Concat sozinho nos caminhos padrão. Se não detectar, informe o executável em
**Configurações → IA local → Executável do Concat**. Os dois programas conversam pelo servidor MCP embutido no
Concat (`concat --mcp headless`), como processos separados: nenhum código do Concat (licença AGPL-3.0) é
incorporado ao ClipFlow.

#### Motor "Edição com IA (Concat)"

Ao criar o projeto, escolha o motor **Edição com IA (Concat)**. Cada Short passa a ser montado e exportado pelo
Concat, com:

- **Zoom de ênfase:** aproximação suave de 12% nas frases com mais marcas de ênfase (exclamações, números,
  "nunca", "mudou minha vida"…). No máximo um zoom a cada ~8 s, e nunca no layout dividido.
- **Texto de gancho:** o melhor título sugerido aparece no topo nos primeiros ~2,6 s. Ele só usa frases reais da fala.
- Legendas editáveis e o projeto salvo: dá para abrir no Concat e ajustar depois.

O enquadramento e a remoção de pausas continuam sendo feitos pelo FFmpeg do ClipFlow. Se o Concat falhar ou não
estiver instalado, o corte sai pelo FFmpeg automaticamente, e o motivo fica registrado.

> No Concat, as legendas vêm por frase. O destaque animado palavra a palavra continua existindo apenas no motor
> "Rápido (FFmpeg)".

---

## Direitos autorais e YouTube

- Use apenas conteúdo **próprio** ou com **autorização/licença** do titular. O app registra a origem do vídeo, a base
  legal e a documentação da autorização em `ClipFlowStudio/projects/<id>/project.json`.
- O download do YouTube (yt-dlp) aceita só vídeos públicos e individuais. Vídeos privados, com restrição de idade,
  exclusivos para membros, ao vivo ou com DRM são recusados — **o app não usa cookies nem contorna proteções**.
  Os Termos do YouTube restringem downloads: use somente com permissão do titular.
- Cortes de terceiros podem gerar **reivindicações de Content ID**. Adicionar legendas **não** torna o conteúdo
  original e **não garante monetização** — o YouTube exige contribuição editorial relevante.
- A "pontuação editorial" estima clareza, contexto e coerência do trecho. **Não é previsão de visualizações.**

---

## Arquitetura

```
clipflow-studio/
├── backend/                 Python 3 + FastAPI
│   ├── app/
│   │   ├── main.py          API + serve a interface compilada
│   │   ├── worker.py        fila persistente (SQLite), concorrência, cancelamento, tentativas
│   │   ├── config.py        config.toml + ajustes salvos pela interface
│   │   ├── db.py            SQLite (projetos, cortes, tarefas, configurações)
│   │   ├── storage.py       pastas por projeto, proteção de caminhos
│   │   ├── security.py      validação de URL, arquivos e declaração de direitos
│   │   ├── api/             rotas: projetos, cortes/biblioteca, uploads, sistema
│   │   ├── pipeline/
│   │   │   ├── youtube.py     metadados e download autorizado (yt-dlp)
│   │   │   ├── ffmpeg.py      probe, execução com progresso real, verificação de integridade
│   │   │   ├── transcribe.py  faster-whisper (timestamps por palavra) ou importação de SRT/VTT
│   │   │   ├── audio.py       energia/clipping do áudio (qualidade por trecho)
│   │   │   ├── selection.py   frases → candidatos → 7 critérios → seleção sem sobreposição
│   │   │   ├── llm.py         Ollama opcional (reavaliação e textos)
│   │   │   ├── framing.py     MediaPipe/Haar, rastreamento, câmera suave, layouts
│   │   │   ├── subtitles.py   ASS com destaque por palavra (Classic, Neon, Minimal, Impact)
│   │   │   ├── render.py      remoção de pausas, filtros FFmpeg, H.264/AAC
│   │   │   ├── metadata.py    títulos, descrição, hashtags
│   │   │   ├── editing.py     correção de legenda mantendo a sincronização
│   │   │   ├── concat_bridge.py  ponte MCP com o editor Concat (opcional)
│   │   │   ├── enhance.py     zoom de ênfase e texto de gancho (motor Concat)
│   │   │   └── runner.py      orquestra análise e renderização
│   │   └── assets/          modelos de rosto (BlazeFace, Haar) e fontes (Poppins, Anton — OFL)
│   └── tests/               95 testes (pytest), incluindo ponta a ponta com vídeo real
├── frontend/                Vue 3 + Vite + Tailwind CSS
├── ClipFlowStudio/          dados (criado na 1ª execução)
│   ├── projects/<id>/  downloads/<id>/  transcripts/<id>/  clips/<id>/
│   ├── subtitles/<id>/  exports/<id>/  logs/<id>.log  clipflow.db
├── config.example.toml
├── setup-windows.bat  start-windows.bat  start.sh
└── docs/STATUS.md
```

**Fluxo**: `analyze` (obter vídeo → extrair áudio 16 kHz → transcrever → pontuar e selecionar) →
`awaiting_review` (opcional) → `render` (para cada corte: enquadramento → remoção de pausas → legendas ASS →
FFmpeg → verificação → miniatura → títulos).

**Segurança**: comandos externos sempre como lista de argumentos (sem shell); nomes de arquivo enviados nunca viram
caminho em disco; IDs validados por regex; todo arquivo servido é conferido dentro da pasta de dados; upload com
limite de tamanho e validação por FFprobe; servidor ouve só em `127.0.0.1` por padrão; token de acesso opcional
(`server.access_token`) para uso na rede local.

## Desenvolvimento

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest            # 95 testes (~3 min; gera vídeos de teste com FFmpeg)
python -m app --no-browser  # API em :8000

cd ../frontend
npm run dev                 # interface com recarga automática em :5173 (proxy para :8000)
```

API documentada automaticamente em <http://127.0.0.1:8000/docs>.

## Licenças de terceiros

Fontes Poppins e Anton: SIL Open Font License (`backend/app/assets/fonts/OFL-*.txt`).
Modelo BlazeFace (MediaPipe): Apache 2.0. Haar cascade (OpenCV): licença Intel/BSD.
