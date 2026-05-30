# Good Vibes — Bot Discord

[![Testes](https://github.com/coddingFW/DiscordBot/actions/workflows/tests.yml/badge.svg)](https://github.com/coddingFW/DiscordBot/actions/workflows/tests.yml)
[![Cobertura](https://codecov.io/gh/coddingFW/DiscordBot/graph/badge.svg)](https://codecov.io/gh/coddingFW/DiscordBot)

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
| `!warn @membro <motivo>` | Registra aviso (histórico persistente, DM automática) |
| `!warns @membro` | Exibe o histórico completo de avisos |
| `!delwarn <id>` | Remove um aviso específico pelo ID |
| `!clearwarns @membro` | Apaga todos os avisos do membro (admin) |

> **Ações automáticas:** 3 avisos → mute automático · 5 avisos → ban automático. Tudo registrado no canal de logs.

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

## Testes

### Testes automatizados

O projeto usa **pytest** com cobertura de código via **Codecov**. Os testes rodam automaticamente a cada push via GitHub Actions.

```bash
# Instalar dependências de dev
pip install -r requirements-dev.txt

# Rodar todos os testes
pytest

# Rodar com relatório de cobertura
pytest --cov=cogs --cov=bot --cov-report=term-missing
```

| Módulo | Cobertura | O que é testado |
|---|---|---|
| `warns.py` | 96% | Registro, contador, auto-mute, auto-ban, delwarn, clearwarns |
| `utility.py` | 96% | ping, uptime, serverinfo, userinfo, avatar, botinfo, say, embed |
| `moderation.py` | 91% | kick, ban, unban, purge, mute, unmute |
| `playlist.py` | 79% | CRUD completo de playlists no SQLite |
| `logs.py` | 66% | log_embed, send_log, listeners de join/delete |
| `ai.py` | 25% | Limpeza TTS, anti-injection, erros amigáveis, rate limit, presets |
| `music.py` | 26% | Cache de busca, detecção de URLs, formatação de duração |

> Partes que dependem de conexão real com Discord (voz, playback) ou APIs externas (Gemini, edge-tts) são cobertas pelos testes manuais abaixo.

---

### Checklist de testes manuais

Execute este checklist antes de cada deploy em produção.

#### Música

- [ ] `!m <nome da música>` — bot entra no canal de voz e começa a tocar
- [ ] Painel de controle aparece com os botões ⏸ ⏭ 🔀 🔁 ⏹
- [ ] Botão ⏸ pausa a música (ícone muda para ▶️)
- [ ] Botão ▶️ retoma a música (ícone volta para ⏸)
- [ ] Botão ⏭ pula para a próxima música
- [ ] Botão 🔁 ativa o loop (botão fica verde), `!m` de nova música adiciona à fila
- [ ] Botão 🔀 embaralha a fila
- [ ] Botão ⏹ para a música e desconecta o bot
- [ ] `!m <URL do YouTube>` toca por link direto
- [ ] `!m <URL de playlist do YouTube>` carrega todas as faixas na fila
- [ ] `!m <URL do Spotify — faixa>` converte e toca no YouTube
- [ ] `!m <URL de playlist do Spotify>` carrega todas as faixas
- [ ] `!m <URL do SoundCloud>` toca faixa do SoundCloud
- [ ] Bot desconecta automaticamente após 2 minutos sem tocar
- [ ] Bot reconecta automaticamente após queda de conexão de voz

#### Moderação e Avisos

- [ ] `!warn @membro motivo` — registra aviso, envia DM ao membro, mostra `Aviso #1`
- [ ] `!warn` no mesmo membro 2x — mostra `Aviso #2` e avisa que próximo aplicará mute
- [ ] `!warn` no mesmo membro 3x — aplica **mute automático**, cargo "Muted" é criado/atribuído
- [ ] `!warn` no mesmo membro 4x e 5x — no 5º aplica **ban automático**
- [ ] `!warns @membro` — exibe histórico com ID, data, motivo e moderador
- [ ] `!delwarn <id>` — remove aviso específico do histórico
- [ ] `!clearwarns @membro` — limpa todos os avisos, requer permissão de admin
- [ ] `!kick @membro motivo` — expulsa e registra no canal de logs
- [ ] `!ban @membro motivo` — bane e registra no canal de logs
- [ ] `!unban <ID>` — remove o ban
- [ ] `!purge 10` — apaga 10 mensagens do canal
- [ ] `!mute @membro` — silencia o membro em todos os canais
- [ ] `!unmute @membro` — remove o silêncio

#### Logs de auditoria

- [ ] Canal `#logs` recebe log ao usar `!kick`, `!ban`, `!warn`, `!mute`
- [ ] Canal `#logs` registra quando um membro entra no servidor
- [ ] Canal `#logs` registra quando uma mensagem é deletada
- [ ] Canal `#logs` registra ban/unban feito pelo painel do Discord (não só por comando)

#### Playlists

- [ ] `!playlist criar <nome>` — cria playlist
- [ ] `!playlist add <nome> <música>` — adiciona música à playlist
- [ ] `!playlist ver <nome>` — lista as músicas com numeração
- [ ] `!playlist tocar <nome>` — coloca todas na fila e começa a tocar
- [ ] `!playlist remove <nome> <nº>` — remove música e renumera corretamente
- [ ] `!playlist deletar <nome>` — remove playlist e todas as músicas
- [ ] `!playlist lista` — exibe todas as playlists do servidor

#### Assistente IA

- [ ] Mensagem no canal `#ia` recebe resposta do Gemini
- [ ] Botão 🔊 **Ouvir** gera arquivo de áudio e envia em DM privada
- [ ] "toca <música>" no canal IA — bot entra na voz e toca
- [ ] "pula a música" no canal IA — pula a faixa atual
- [ ] "para a música" no canal IA — para e desconecta
- [ ] "cria um canal chamado X" — cria o canal (pede permissão de gerenciar canais)
- [ ] "publica X no canal #geral" — envia mensagem no canal correto
- [ ] "quem tá online?" — lista membros online
- [ ] Ação destrutiva (kick/ban/deletar canal) exibe botão de **Confirmação** antes de executar
- [ ] Mensagem com "ignore previous instructions" é bloqueada (anti-injection)
- [ ] `!ia-canal #canal` — muda o canal onde a IA responde
- [ ] `!ia-tom formal` — IA passa a responder em tom formal
- [ ] `!ia-voz antonio` — botão 🔊 Ouvir usa a voz masculina
- [ ] `!ia-limpar` — IA "esquece" o histórico de conversa do canal
- [ ] Rate limit: mais de 5 mensagens por minuto exibe aviso e ignora o excesso

#### Utilitários

- [ ] `!ping` — exibe latência em ms com cor (verde/laranja/vermelho)
- [ ] `!uptime` — exibe tempo online corretamente
- [ ] `!serverinfo` — exibe informações do servidor com ícone
- [ ] `!userinfo @membro` — exibe cargos, datas e avatar
- [ ] `!botinfo` — exibe número de servidores e latência atual

---

## Dependências

| Pacote | Uso |
|---|---|
| `discord.py` | Framework do bot |
| `davey` | Protocolo de voz do Discord (DAVE) |
| `yt-dlp` | Stream de áudio do YouTube |
| `google-genai` | API do Gemini |
| `python-dotenv` | Variáveis de ambiente |
