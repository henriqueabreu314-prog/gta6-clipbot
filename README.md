# GTA 6 Clip Bot

Bot que corre **na nuvem (GitHub Actions, grátis)**, sem precisar do teu PC:

1. De 3 em 3 horas procura os clips de GTA 6 mais vistos dos streamers que escolheres na **Twitch e/ou na Kick**.
2. Faz o download do clip e converte-o para vertical (9:16), com:
   - título grande no topo;
   - legendas automáticas (Whisper);
   - crédito ao streamer;
   - a tua marca de água.
3. Manda-te o vídeo no **Telegram** com os botões ✅ Publicar e ❌ Rejeitar.
4. Os aprovados entram numa fila e são publicados nas **horas marcadas** no YouTube Shorts e no TikTok.

Para passar a ser 100% automático, muda `approval: true` para `false` no `config.yaml`.

---

## Passo 1 — Criar o repositório no GitHub

1. Cria uma conta em https://github.com.
2. Carrega em **New repository**, dá-lhe um nome (ex.: `gta6-clipbot`) e escolhe **Public**. Num repositório público os minutos do GitHub Actions são ilimitados. As chaves continuam secretas.
3. Carrega em **uploading an existing file** e arrasta todos os ficheiros desta pasta, incluindo a pasta `.github`.

## Passo 2 — Twitch (só se usares streamers da Twitch)

A Kick não precisa de chaves; podes saltar este passo se só usares a Kick.

1. Vai a https://dev.twitch.tv/console, faz login e carrega em **Register Your Application**.
2. Preenche assim:
   - Nome: qualquer;
   - OAuth Redirect URL: `http://localhost`;
   - Categoria: *Other*;
   - Client type: *Confidential*.
3. Copia o **Client ID** e gera um **Client Secret**.

## Passo 3 — Telegram (aprovação e notificações)

1. No Telegram, fala com **@BotFather**, envia `/newbot` e segue os passos. No fim recebes o **token** do bot.
2. Abre o teu bot novo e envia-lhe qualquer mensagem (ex.: "olá").
3. No browser, abre `https://api.telegram.org/botTOKEN/getUpdates`, trocando `TOKEN` pelo teu token.
4. Procura `"chat":{"id": 123456789` na página. Esse número é o teu **chat id**.

## Passo 4 — Guardar as chaves no GitHub

No repositório, vai a **Settings → Secrets and variables → Actions → New repository secret** e cria:

| Nome | Valor |
|---|---|
| `TWITCH_CLIENT_ID` | Client ID da Twitch |
| `TWITCH_CLIENT_SECRET` | Client Secret da Twitch |
| `TELEGRAM_BOT_TOKEN` | token do BotFather |
| `TELEGRAM_CHAT_ID` | o teu chat id |

## Passo 5 — Configurar

Edita o `config.yaml` no próprio site do GitHub (ícone do lápis):

- `streamers`: os nomes na Twitch e/ou na Kick (o que aparece no link do canal). **Usa só streamers que autorizam clips**, por exemplo os que têm campanhas de clippers no Whop (Content Rewards) ou regras de clipping no painel do canal.
- `watermark.text`: o @ do teu canal.
  - Para usares um logótipo, carrega um PNG (ex.: `assets/logo.png`) e põe o caminho em `watermark.logo`.
- `schedule`: o fuso horário e as horas de publicação.

## Passo 6 — Testar

1. Vai a **Actions → Preparar clips → Run workflow**, marca **Teste** e carrega em Run.
2. Quando acabar, aparece em baixo o ficheiro **videos-teste** para download. Vê se os vídeos estão bem.
3. Corre outra vez **sem** marcar Teste. Os vídeos chegam ao Telegram com os botões.

A partir daqui tudo corre sozinho. Mesmo sem YouTube nem TikTok ligados, à hora marcada o bot avisa-te no Telegram com o título e a descrição prontos, para publicares à mão a partir do telemóvel.

---

## Passo 7 (opcional) — Publicação automática no YouTube

> ⚠️ A Google só deixa uma app publicar vídeos **públicos** depois de passar uma auditoria, que é grátis. Até lá, os vídeos enviados pela API ficam **privados**. Pede a auditoria no formulário "YouTube API Services – Audit and Quota Extension". Entretanto podes publicar à mão a partir do Telegram.

1. Em https://console.cloud.google.com, cria um projeto e ativa a **YouTube Data API v3**.
2. Configura o **OAuth consent screen**: escolhe *External*, adiciona o teu email e depois carrega em **Publish app** (estado *In production*). Se ficar em *Testing*, a chave expira ao fim de 7 dias.
3. Em **Credentials → Create credentials → OAuth client ID**:
   - Tipo: *Web application*;
   - Authorized redirect URI: `https://developers.google.com/oauthplayground`.

   Copia o Client ID e o Client Secret.
4. Abre https://developers.google.com/oauthplayground.
   1. Na ⚙️, marca **Use your own OAuth credentials** e cola o Client ID e o Client Secret.
   2. Na lista, escreve o scope `https://www.googleapis.com/auth/youtube.upload`, carrega em **Authorize APIs** e entra com a conta do canal.
   3. Carrega em **Exchange authorization code for tokens** e copia o **Refresh token**.
5. Cria os secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET` e `YT_REFRESH_TOKEN`.

O limite é de cerca de 6 uploads por dia com a quota grátis.

## Passo 8 (opcional) — TikTok

> ⚠️ O TikTok também exige que a tua app seja aprovada antes de publicar vídeos públicos. Até lá só publica em privado (`SELF_ONLY`).

1. Cria uma app em https://developers.tiktok.com com **Login Kit** e **Content Posting API** (Direct Post) e submete-a para revisão.
2. Faz o login OAuth com o scope `video.publish` para obteres o **refresh token**, que é válido por 1 ano.
3. Cria os secrets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` e `TIKTOK_REFRESH_TOKEN`.
4. No `config.yaml`, põe `tiktok.enabled: true`.

---

## Notas

- **Kick:** a Kick não tem uma API oficial para listar clips, por isso o bot usa o mesmo endpoint que o site kick.com usa. Se a Kick bloquear os pedidos do GitHub (aparece "bloqueio da Cloudflare?" nos logs), diz-me para trocarmos por um serviço de API de terceiros.

- O ficheiro `data/state.json` guarda os clips que já foram usados, aprovados ou publicados. Não o apagues.
- O GitHub pode atrasar os agendamentos entre 5 e 30 minutos. É normal.
- Os vídeos ficam guardados no próprio Telegram, por isso não precisas de Google Drive nem de servidor.
