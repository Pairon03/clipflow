# ClipFlow Studio

App local (Windows) que transforma podcasts autorizados em Shorts/TikToks: FastAPI + SQLite (`backend/`),
Vue 3 + Tailwind 4 (`frontend/`), FFmpeg, faster-whisper, MediaPipe/OpenCV, Ollama local opcional.
Respostas e textos da interface em português do Brasil. Testes: `cd backend && python -m pytest`.

## Skills do projeto
Usar: run (abrir o app e conferir telas no navegador), code-review (revisar o diff antes de cada commit)
Depois: security-review (antes de uma versão pública: OAuth, tokens, rotas), session-start-hook (quando as sessões
na nuvem precisarem preparar FFmpeg/dependências sozinhas), frontend-design (fase de acabamento visual),
huggingface-local-models (se for trocar o modelo local do Ollama), data:analyze (fase de métricas dos vídeos)
Não usar: claude-api, image-generation, canva, cloudinary (serviços pagos/externos); marketing e searchfit-seo
(o app já gera títulos/descrições pela fala; SEO de site não se aplica); design-taste-frontend, refero, prototype,
simplify (duplicam as escolhidas); Unity, Zoom, Office e demais fora do domínio
Regra: o render é sempre o FFmpeg do ClipFlow (Concat só como motor opcional já integrado); sem APIs pagas —
IA só local (Ollama); usar só conteúdo próprio ou autorizado; nunca inventar falas.
