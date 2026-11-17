# Explicação animada (motion graphics)

Opcional e **desligada por padrão**. Liga em *Criar Shorts*, *Preferências* ou na página do projeto, seção
**Explicação animada**.

## O que faz
- Blocos curtos (4–8 s, até 3 por corte) em fundo claro, **intercalados com o podcast** — sempre há pelo menos 4 s
  de podcast entre dois blocos.
- Cenas: **título + ícone**, **número grande**, **cartões** (nomes citados) e **comparação** (antes/depois).
- **Rosto em bolha**: quem está falando aparece num círculo embaixo durante a animação (opção "Rosto em bolha").
- **Teaser**: ~1 s da cena mais forte no começo do vídeo, para prender a atenção (opção "Teaser no 1º segundo").
- A legenda continua por cima, grande.

## Onde a animação entra
- **Automático**: o app procura os momentos mais visuais da fala (números, nomes, comparações, palavras com ícone).
- **No começo**: o primeiro bloco abre o corte.
- Em cada corte, o editor **Explicação animada** deixa trocar o modo (Igual ao projeto / Automático / No começo /
  Sem animação), mudar os tempos dos blocos e os textos, tipo e ícone de cada cena. *Voltar à sugestão* desfaz.
  Depois de salvar, renderize o corte de novo.

## Regras
- **Os textos vêm só da fala.** O roteiro automático usa as palavras ditas; se o Ollama estiver ligado, ele
  reescreve as cenas numa única chamada por corte, e qualquer palavra ou número que não foi dito é descartado.
- Tudo é desenhado localmente (Pillow) e montado pelo FFmpeg do ClipFlow — nada de serviço externo.
- Ícones: [Lucide](https://lucide.dev) (licença ISC, em `backend/app/assets/icons/LICENSE-lucide.txt`);
  para gerar de novo: `python -m app.tools.build_icons` (só no desenvolvimento).

## Limites conhecidos
- A sugestão automática é heurística: funciona bem com números e nomes, e mal em falas abstratas — aí use o editor.
- No layout com faixa/foto em cima a bolha do rosto fica desligada.
- Temas de cor ficam para a próxima etapa.
