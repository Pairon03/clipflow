# Publicar no YouTube (e legenda pronta para o TikTok)

O ClipFlow envia os Shorts direto para o **seu** canal pela API oficial do YouTube (YouTube Data API v3), que é
gratuita. Título, descrição, tags e categoria saem do que o app já gerou (e do que você editou). O agendamento é
feito pelo próprio YouTube: o vídeo sobe na hora e é publicado no horário marcado, mesmo com o PC desligado.

## Configurar (uma vez, ~15 min)

1. Entre em [console.cloud.google.com](https://console.cloud.google.com/) com a conta Google do canal e crie um
   projeto (ex.: "ClipFlow"). Não precisa de cartão.
2. **APIs e serviços › Biblioteca**: ative a **YouTube Data API v3**.
3. **Tela de consentimento OAuth** (em alguns painéis: "Google Auth Platform"): tipo **Externo**, nome "ClipFlow",
   seu e-mail como contato. Em **Público-alvo / Usuários de teste**, adicione o seu e-mail.
4. Ainda nessa tela, clique em **Publicar app** ("Em produção"). No modo "Teste" o Google derruba a autorização a
   cada 7 dias. Não é preciso enviar o app para verificação.
5. **Credenciais › Criar credenciais › ID do cliente OAuth › App para computador**. Baixe o JSON.
6. No ClipFlow, aba **Publicar**: *Enviar client_secret.json* e depois *Conectar conta do YouTube*. O Google mostra
   "O Google não verificou este app": clique em **Avançado › Acessar ClipFlow** (o app é seu) e permita o envio de
   vídeos e a leitura do canal.

A conexão precisa ser feita **no próprio computador onde o ClipFlow roda** (endereço `http://127.0.0.1:8000`): o
Google devolve a autorização só para esse endereço. Depois de conectado, dá para usar o app de outro aparelho
normalmente.

## Usar

- **Biblioteca**: marque os Shorts e clique em **Publicar no YouTube**. Ou use o botão **YouTube** de cada Short
  (também na página do projeto).
- Escolha **Agendar** (data inicial + horários, um vídeo por horário; horários já ocupados são pulados),
  **Privado**, **Não listado** ou **Público agora**.
- Escolha qual dos títulos sugeridos vai em cada vídeo (ou edite). Descrição e hashtags são as do corte; edite antes
  pelo lápis do Short, se quiser.
- A aba **Publicar** mostra a fila: progresso do envio, horário agendado, link do vídeo e do YouTube Studio,
  cancelar e tentar de novo.
- O mesmo corte não é enviado duas vezes, a não ser que você marque "Enviar de novo".

## Limites do Google (importante)

- **Vídeos privados até a auditoria.** Projetos novos do Google Cloud que não passaram pela auditoria da API
  do YouTube têm os vídeos enviados pela API travados como **privados**, inclusive os agendados. Até lá, abra o
  YouTube Studio (botão *Studio* na fila) e publique/agende com um clique. Para tirar a trava, preencha o formulário
  gratuito **YouTube API Services – Audit and Quota Extension** do Google (leva algumas semanas).
- **Limite diário de envios.** A cota padrão do projeto limita quantos vídeos sobem por dia (o custo de cada envio é
  definido pelo Google; confira em *APIs e serviços › YouTube Data API v3 › Cotas*). Quando o limite acaba, o envio
  fica como **"Limite do dia"** e o ClipFlow tenta de novo sozinho depois da virada da cota (meia-noite no horário
  do Pacífico, ~4h ou 5h em Brasília).
- Se o horário agendado passar enquanto o vídeo espera na fila (ex.: limite do dia), ele é publicado assim que subir,
  e a fila avisa.

## Como funciona por dentro

- `backend/app/youtube_api.py`: OAuth com PKCE e redirecionamento para `http://127.0.0.1:<porta>`; envio retomável
  em partes de 8 MB. Só biblioteca padrão do Python, sem dependências novas.
- `backend/app/publisher.py`: fila própria (tabela `publications`), um envio por vez, separada da fila de render.
  Queda de internet: espera crescente (30 s → 30 min, até 6 tentativas) e continua da parte onde parou. Reinício do
  app: o envio volta para a fila e retoma a mesma sessão. Autorização revogada: a fila pausa e pede para reconectar.
- Arquivos em `ClipFlowStudio/youtube/` (`client_secret.json`, `token.json`, só leitura do dono quando o sistema
  permite). O token nunca é devolvido pela API do ClipFlow.
- Título sem `<` `>` e com até 100 caracteres; descrição até 5.000 bytes; tags = hashtags sem `#` + palavras-chave,
  até 500 caracteres; vídeo marcado como "não é conteúdo para crianças".

## O que foi testado

- 9 testes contra um **servidor falso do Google** que segue o protocolo documentado (`backend/tests/fake_google.py`):
  autorização com PKCE, recusa da autorização, envio em 3 partes com conferência dos bytes, retomada após erro 503 na
  2ª parte (mesma sessão), limite diário, autorização revogada, cancelar/tentar de novo, validação do agendamento e
  regras de título/descrição/tags.
- **Não testado com uma conta real**: daqui não há acesso à sua conta Google. Faça o primeiro envio com **um vídeo
  em "Privado"** e confira no YouTube Studio antes de agendar em lote.

## TikTok

A API de postagem do TikTok exige um app de desenvolvedor aprovado; antes disso só permite rascunhos ou vídeos
privados. Por enquanto, cada Short tem o botão **Legenda TikTok**: copia título + descrição + hashtags prontos para
colar ao subir o MP4 pelo TikTok (no navegador ou no celular).
