# Good Vibes — Bot Discord

Bot multifuncional para Discord com música, moderação, playlists e assistente de IA (Gemini).

---

## Como adicionar ao seu servidor

[Clique aqui para adicionar o Good Vibes ao seu servidor](https://discord.com/oauth2/authorize?client_id=1342734639680454707&permissions=271673414&integration_type=0&scope=bot)

> O bot precisa que alguém com permissão de **Gerenciar Servidor** aceite o convite.

---

## Comandos

O prefixo padrão é `!`. Use `!help` no Discord para ver a lista completa.

### Música

| Comando | Aliases | Descrição |
|---|---|---|
| `!m <música/URL>` | `!tocar` | Toca uma música do YouTube |
| `!pause` | `!pausar` | Pausa a música |
| `!resume` | `!continuar` | Retoma a música pausada |
| `!skip` | `!s`, `!pular` | Pula para a próxima |
| `!stop` | `!parar` | Para tudo e desconecta |
| `!volume <0-100>` | `!vol` | Ajusta o volume |
| `!nowplaying` | `!np`, `!tocando` | Música atual |
| `!queue` | `!fila`, `!q` | Fila de músicas |
| `!loop` | — | Ativa/desativa loop |
| `!clear` | `!limpar` | Limpa a fila |
| `!remove <nº>` | `!remover` | Remove música da fila |
| `!join` | `!entrar` | Entra no canal de voz |

> O bot desconecta automaticamente após 2 minutos de inatividade.

---

### Playlists

Playlists são salvas no servidor e persistem entre reinicializações.

| Comando | Descrição |
|---|---|
| `!playlist criar <nome>` | Cria uma nova playlist |
| `!playlist add <nome> <música>` | Adiciona uma música (nome ou URL) |
| `!playlist ver <nome>` | Lista as músicas da playlist |
| `!playlist tocar <nome>` | Coloca todas as músicas na fila |
| `!playlist remove <nome> <nº>` | Remove uma música pelo número |
| `!playlist deletar <nome>` | Apaga a playlist |
| `!playlist lista` | Lista todas as playlists salvas |

Também funciona com `!pl` como atalho.

---

### Moderação

Requer as permissões correspondentes no servidor.

| Comando | Descrição |
|---|---|
| `!kick @membro [motivo]` | Expulsa um membro |
| `!ban @membro [motivo]` | Bane um membro |
| `!unban <Nome#0000 ou ID>` | Remove o ban |
| `!purge <1-100>` | Apaga até 100 mensagens |
| `!mute @membro [motivo]` | Silencia um membro |
| `!unmute @membro` | Remove o silêncio |
| `!warn @membro <motivo>` | Envia aviso por DM |

---

### Utilitários

| Comando | Aliases | Descrição |
|---|---|---|
| `!ping` | — | Latência do bot |
| `!uptime` | — | Tempo online |
| `!botinfo` | `!sobre` | Informações do bot |
| `!serverinfo` | `!servidor` | Informações do servidor |
| `!userinfo [@membro]` | `!usuario`, `!perfil` | Informações de um usuário |
| `!avatar [@membro]` | — | Avatar de um usuário |
| `!say <mensagem>` | — | Bot envia uma mensagem |
| `!embed <título> <desc>` | — | Bot envia um embed |

---

### Assistente IA (Gemini)

Por padrão, a IA responde no canal de texto chamado **`ia`**. Crie esse canal no seu servidor e pronto: **qualquer mensagem enviada nele é respondida pelo Gemini** (não precisa de comando, é só escrever normalmente).

A IA pode executar ações reais no servidor, como:
- "toca uma música do kendrick lamar"
- "entra na sala Geral"
- "cria um canal de voz chamado gaming"
- "publica um resumo sobre a Física no canal material-academico"
- "quem tá online agora?"

Outros recursos:
- **🔊 Ouvir** — cada resposta da IA tem um botão que gera o áudio (TTS) da mensagem, enviado de forma privada só pra você.
- **Confirmação de segurança** — ações destrutivas (deletar canal, banir, expulsar) só acontecem depois que você clica em **Confirmar**.

#### Comandos da IA (configuração por servidor)

Estes comandos exigem permissão de **Gerenciar Canais** e valem só para o servidor onde forem usados:

| Comando | Descrição |
|---|---|
| `!ia-limpar` | Limpa o histórico de conversa do canal (a IA "esquece" o papo anterior) |
| `!ia-canal #canal` | Define em qual canal a IA responde neste servidor |
| `!ia-canal` | Mostra qual canal está configurado |
| `!ia-canal-padrao` | Volta a IA para o canal padrão (`ia`) |
| `!ia-tom <opção>` | Muda a tonalidade: `informal`, `formal`, `neutro`, `tecnico`, `divertido` |
| `!ia-tom` | Mostra o tom atual e lista as opções |
| `!ia-voz <opção>` | Muda a voz do áudio: `thalita`, `francisca`, `giovanna`, `leticia`, `antonio`, `fabio`, `humberto` |
| `!ia-voz` | Mostra a voz atual e lista as opções |

> **Tom × Voz:** o *tom* muda **como** a IA escreve (e o áudio acompanha, pois lê o texto); a *voz* muda **o timbre** de quem lê o áudio. Dá pra combinar (ex: `!ia-tom formal` + `!ia-voz humberto`).

#### Primeiros passos (depois de adicionar o bot pelo link)

1. **Adicione o bot** ao servidor pelo link de convite (precisa de permissão de Gerenciar Servidor).
2. **Crie um canal de texto** com o nome que quiser — `ia`, `robô`, `assistente`, etc.
3. Se o nome **não** for `ia`, avise o bot qual canal usar:
   ```
   !ia-canal #seu-canal
   ```
   (Se usar `ia`, nem precisa: já funciona por padrão.)
4. **(Opcional)** ajuste o estilo e a voz:
   ```
   !ia-tom formal
   !ia-voz antonio
   ```
5. Pronto! Escreva qualquer mensagem no canal e a IA responde.

> 💡 Cada servidor tem sua própria configuração (canal, tom e voz), salva e mantida entre reinicializações.

---

## Configuração

### Pré-requisitos

- Python 3.12+
- FFmpeg instalado e no PATH
- Conta no [Discord Developer Portal](https://discord.com/developers/applications)
- Chave de API do [Google AI Studio](https://aistudio.google.com/apikey) (para a IA)

### Instalação

```bash
git clone https://github.com/coddingFW/DiscordBot.git
cd DiscordBot/bot_discord

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### Configuração do .env

```bash
cp .env.example .env
```

```env
DISCORD_TOKEN=seu_token_aqui
BOT_PREFIX=!
GOOGLE_API_KEY=sua_chave_gemini_aqui
AI_CHANNEL_NAME=ia
AI_MODEL=gemini-2.5-flash
LOG_CHANNEL_NAME=logs
SPOTIPY_CLIENT_ID=seu_client_id_aqui
SPOTIPY_CLIENT_SECRET=seu_client_secret_aqui
```

| Variável | Obrigatória? | O que faz |
|---|---|---|
| `DISCORD_TOKEN` | ✅ Sim | Token do bot (Discord Developer Portal) |
| `BOT_PREFIX` | Não (padrão `!`) | Símbolo dos comandos: `!ping`, `!m`... |
| `GOOGLE_API_KEY` | Pra IA | Chave do Gemini ([Google AI Studio](https://aistudio.google.com/apikey)) |
| `AI_CHANNEL_NAME` | Não (padrão `ia`) | **Nome do canal onde a IA responde.** Troque pra usar outro canal (ex: `Robô`) |
| `AI_MODEL` | Não (padrão `gemini-2.5-flash`) | Versão do Gemini. Se uma versão der erro de cota, tente outra |
| `LOG_CHANNEL_NAME` | Não (padrão `logs`) | Canal onde os logs de moderação são registrados |
| `SPOTIPY_CLIENT_ID` / `_SECRET` | Não | Pra tocar links do Spotify (opcional) |

> Não use aspas nem espaços ao redor do `=`. Certo: `AI_CHANNEL_NAME=Robô`. Errado: `AI_CHANNEL_NAME = "Robô"`.
> Toda vez que mudar o `.env`, **reinicie o bot** pra valer.

### Executando

```bash
.venv\Scripts\python.exe bot.py
```

---

## Permissões necessárias

- **Gerais:** Expulsar membros, Banir membros, Gerenciar cargos, Gerenciar canais
- **Texto:** Enviar mensagens, Gerenciar mensagens, Ver histórico, Inserir links
- **Voz:** Conectar, Falar

---

## Dependências

| Pacote | Uso |
|---|---|
| `discord.py` | Framework do bot |
| `davey` | Protocolo de voz do Discord (DAVE) |
| `yt-dlp` | Stream de áudio do YouTube |
| `google-genai` | API do Gemini |
| `python-dotenv` | Variáveis de ambiente |
