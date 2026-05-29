import os
import time
import logging
import re
import asyncio
import tempfile
import unicodedata
from collections import deque
import aiosqlite
import discord
from discord.ext import commands
from google import genai
from google.genai import types
import edge_tts

log = logging.getLogger("cog.ai")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_CHANNEL_NAME = os.getenv("AI_CHANNEL_NAME", "ia")  # nome padrão (fallback global)
AI_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "ai_config.db")
TTS_VOICE = os.getenv("TTS_VOICE", "pt-BR-ThalitaNeural")
TTS_RATE = os.getenv("TTS_RATE", "-3%")   # leve desaceleração soa mais natural
TTS_PITCH = os.getenv("TTS_PITCH", "+2Hz")

# Vozes pt-BR disponíveis (edge-tts): chave -> (rótulo amigável, id da voz)
VOICE_PRESETS = {
    "thalita":   ("Thalita — feminina (padrão)", "pt-BR-ThalitaNeural"),
    "francisca": ("Francisca — feminina",        "pt-BR-FranciscaNeural"),
    "giovanna":  ("Giovanna — feminina jovem",   "pt-BR-GiovannaNeural"),
    "leticia":   ("Letícia — feminina suave",    "pt-BR-LeticiaNeural"),
    "antonio":   ("Antônio — masculina",         "pt-BR-AntonioNeural"),
    "fabio":     ("Fábio — masculina",           "pt-BR-FabioNeural"),
    "humberto":  ("Humberto — masculina grave",  "pt-BR-HumbertoNeural"),
}
DEFAULT_VOICE = "thalita"
MODEL_NAME = os.getenv("AI_MODEL", "gemini-2.5-flash")
MAX_HISTORY = 20
RATE_LIMIT = 5          # mensagens
RATE_WINDOW = 60        # por segundo
MAX_INPUT_LEN = 1000    # caracteres por mensagem

# Padrões suspeitos de prompt injection
_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |previous |prior |above )?instructions?|"
    r"forget (everything|all|your instructions?)|"
    r"new instructions?:|"
    r"system( prompt)?:|"
    r"você agora é|now you are|act as (if )?|"
    r"jailbreak|DAN mode|pretend (you are|to be))",
    re.IGNORECASE,
)

def _norm_channel(nome: str) -> str:
    """Normaliza nome de canal: minúsculas, sem acento, espaços→hífen.
    Ajuda a casar 'Material Acadêmico' com 'material-academico'."""
    nome = nome.strip().lower().replace(" ", "-")
    # Remove acentos (NFKD separa o acento; descarta os 'combining marks').
    nome = "".join(c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c))
    return nome


def _is_daily_quota(msg: str) -> bool:
    """True se o erro for o limite DIÁRIO da cota (não adianta tentar de novo hoje)."""
    m = msg.lower()
    return "429" in m and any(
        s in m for s in ("perday", "per day", "generaterequestsperday", "daily", "resource_exhausted", "quota")
    )


def _friendly_error(exc: Exception) -> str:
    """Traduz uma exceção técnica da API em uma mensagem clara para o usuário."""
    msg = str(exc).lower()

    # Cota diária esgotada (free tier = 20 req/dia). Retry não resolve.
    if _is_daily_quota(msg):
        return (
            "📉 **Bati no limite diário de uso da IA.**\n"
            "A chave gratuita do Gemini permite um número limitado de perguntas por dia, "
            "e ele já acabou por hoje. Tenta de novo amanhã que o limite reseta! 🙏"
        )

    # Excesso de requisições em pouco tempo (rate limit por minuto).
    if "429" in msg or "rate" in msg:
        return (
            "⏳ **Tô recebendo perguntas rápido demais!**\n"
            "Espera alguns segundinhos e manda de novo, por favor."
        )

    # Servidor do Gemini sobrecarregado / indisponível.
    if any(s in msg for s in ("503", "unavailable", "overload", "high demand")):
        return (
            "🛠️ **O servidor da IA tá sobrecarregado agora.**\n"
            "Não é culpa sua — tenta mandar a pergunta de novo daqui a pouquinho."
        )

    # Erro interno do servidor.
    if "500" in msg or "internal" in msg:
        return (
            "💥 **Deu um erro interno na IA.**\n"
            "Foi um problema do lado deles. Tenta de novo em instantes."
        )

    # Problema de autenticação / chave de API.
    if any(s in msg for s in ("401", "403", "api key", "permission", "unauthenticated", "invalid_argument")):
        return (
            "🔑 **Tem algo errado com a configuração da IA.**\n"
            "Provavelmente a chave de API. Avisa quem cuida do bot, por favor."
        )

    # Problema de rede / tempo esgotado.
    if any(s in msg for s in ("timeout", "timed out", "connection", "network", "deadline")):
        return (
            "📡 **Não consegui falar com o servidor da IA.**\n"
            "Pode ter sido a conexão. Tenta de novo daqui a pouco."
        )

    # Genérico — não vaza o JSON cru pro usuário.
    return (
        "😅 **Deu um probleminha inesperado ao responder.**\n"
        "Tenta de novo? Se continuar, avisa quem cuida do bot."
    )


# Tonalidades disponíveis: chave -> (rótulo amigável, instrução injetada no prompt)
TONE_PRESETS = {
    "informal": (
        "Descontraído (padrão)",
        "Fale de forma informal, descontraída, como papo entre amigos. "
        "Use gírias brasileiras e emojis quando fizer sentido, sem exagerar. "
        "Respostas curtas — ninguém quer textão. Se o papo for engraçado, entra na brincadeira.",
    ),
    "formal": (
        "Formal e profissional",
        "Fale de maneira formal, educada e profissional. Trate o usuário por você, "
        "evite gírias e emojis, use boa gramática e mantenha um tom respeitoso e claro.",
    ),
    "neutro": (
        "Neutro e objetivo",
        "Fale de forma neutra, objetiva e direta. Sem gírias e sem formalidade excessiva. "
        "Vá direto ao ponto, sem enrolação.",
    ),
    "tecnico": (
        "Técnico e detalhado",
        "Responda de forma técnica, precisa e detalhada, usando os termos corretos da área. "
        "Pode se aprofundar quando o assunto exigir.",
    ),
    "divertido": (
        "Divertido e brincalhão",
        "Seja bem-humorado e brincalhão, solta piadas leves e use emojis à vontade. "
        "Mantenha a energia alta e o clima leve, sem perder a utilidade da resposta.",
    ),
}
DEFAULT_TONE = "informal"

_BASE_PROMPT = """Você é o Good Vibes, assistente do servidor Discord.
{tone}
Responda sempre em português do Brasil.

Você sabe de tudo — história, ciência, cultura pop, tecnologia, curiosidades, o que for. Responda qualquer pergunta normalmente, como alguém bem informado.

Você foi criado por coddingFW. Se alguém perguntar quem te criou ou te desenvolveu, diga que foi o coddingFW e mande o perfil dele no GitHub: https://github.com/coddingFW

Você também tem ferramentas para agir no servidor. Quando o usuário pedir algo que envolva música, canais ou moderação, USE as ferramentas — não explique como fazer, FAÇA.

REGRAS IMPORTANTES sobre canais:
- Para PUBLICAR/POSTAR/ENVIAR/ESCREVER um conteúdo em um canal, use 'publicar_em_canal'. NUNCA use 'criar_canal' para isso.
- Só use 'criar_canal' quando o usuário pedir explicitamente para CRIAR um canal novo.
- Nunca crie o mesmo canal mais de uma vez. Se uma ferramenta disser que o canal já existe ou não foi encontrado, NÃO tente de novo — apenas explique o resultado ao usuário."""


def _build_system_prompt(tone_key: str) -> str:
    """Monta o prompt do sistema com a tonalidade escolhida."""
    _, instrucao = TONE_PRESETS.get(tone_key, TONE_PRESETS[DEFAULT_TONE])
    return _BASE_PROMPT.format(tone=instrucao)

TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="tocar_musica",
            description="Busca e toca uma música ou URL no canal de voz. O bot entra automaticamente no canal de voz do usuário.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Nome da música, artista ou URL do YouTube")
                },
                required=["query"]
            )
        ),
        types.FunctionDeclaration(
            name="entrar_sala_voz",
            description="Entra em um canal de voz específico pelo nome.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "nome_sala": types.Schema(type=types.Type.STRING, description="Nome exato do canal de voz")
                },
                required=["nome_sala"]
            )
        ),
        types.FunctionDeclaration(
            name="sair_sala_voz",
            description="Sai do canal de voz atual.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
        types.FunctionDeclaration(
            name="pular_musica",
            description="Pula a música atual.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
        types.FunctionDeclaration(
            name="parar_musica",
            description="Para a música, limpa a fila e sai da sala de voz.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
        types.FunctionDeclaration(
            name="ver_fila",
            description="Retorna as músicas atualmente na fila.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
        types.FunctionDeclaration(
            name="criar_canal",
            description="Cria um canal de texto ou voz no servidor.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "nome": types.Schema(type=types.Type.STRING, description="Nome do canal"),
                    "tipo": types.Schema(type=types.Type.STRING, description="'texto' ou 'voz'"),
                    "categoria": types.Schema(type=types.Type.STRING, description="Nome da categoria onde criar (opcional)")
                },
                required=["nome", "tipo"]
            )
        ),
        types.FunctionDeclaration(
            name="publicar_em_canal",
            description="Publica/envia uma mensagem de texto em um canal de texto existente, identificado pelo nome. Use isto quando o usuário pedir para 'publicar', 'postar', 'enviar' ou 'escrever' algo em um canal. NÃO crie um canal novo para publicar.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "canal": types.Schema(type=types.Type.STRING, description="Nome do canal de texto onde publicar"),
                    "mensagem": types.Schema(type=types.Type.STRING, description="O conteúdo da mensagem a publicar")
                },
                required=["canal", "mensagem"]
            )
        ),
        types.FunctionDeclaration(
            name="deletar_canal",
            description="Deleta um canal do servidor pelo nome.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "nome": types.Schema(type=types.Type.STRING, description="Nome do canal a deletar")
                },
                required=["nome"]
            )
        ),
        types.FunctionDeclaration(
            name="kick_membro",
            description="Expulsa um membro do servidor.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "membro": types.Schema(type=types.Type.STRING, description="Nome ou apelido do membro"),
                    "motivo": types.Schema(type=types.Type.STRING, description="Motivo do kick")
                },
                required=["membro"]
            )
        ),
        types.FunctionDeclaration(
            name="ban_membro",
            description="Bane um membro do servidor.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "membro": types.Schema(type=types.Type.STRING, description="Nome ou apelido do membro"),
                    "motivo": types.Schema(type=types.Type.STRING, description="Motivo do ban")
                },
                required=["membro"]
            )
        ),
        types.FunctionDeclaration(
            name="desbanir_membro",
            description="Remove o ban de um usuário do servidor. Requer permissão de banir membros.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "identificador": types.Schema(type=types.Type.STRING, description="Nome#0000 ou ID numérico do usuário banido")
                },
                required=["identificador"]
            )
        ),
        types.FunctionDeclaration(
            name="mutar_membro",
            description="Silencia um membro do servidor aplicando o cargo Muted.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "membro": types.Schema(type=types.Type.STRING, description="Nome ou apelido do membro"),
                    "motivo": types.Schema(type=types.Type.STRING, description="Motivo do mute")
                },
                required=["membro"]
            )
        ),
        types.FunctionDeclaration(
            name="desmutar_membro",
            description="Remove o silêncio de um membro do servidor. Requer permissão de gerenciar cargos.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "membro": types.Schema(type=types.Type.STRING, description="Nome ou apelido do membro")
                },
                required=["membro"]
            )
        ),
        types.FunctionDeclaration(
            name="listar_canais",
            description="Lista todos os canais do servidor.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
        types.FunctionDeclaration(
            name="listar_membros_online",
            description="Lista os membros online no servidor.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        ),
    ])
]

# ── Ações destrutivas que precisam de confirmação ──────────────────────────
_DESTRUCTIVE = {"kick_membro", "ban_membro", "desbanir_membro", "desmutar_membro", "deletar_canal"}


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # símbolos, pictogramas, emojis
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # bandeiras
    "\U00002190-\U000021FF"  # setas
    "\U00002B00-\U00002BFF"  # setas/símbolos extras
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


def _clean_for_tts(text: str) -> str:
    """Remove emojis/símbolos e normaliza espaços para uma fala mais natural."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


async def _tts_to_file(text: str, voice: str = TTS_VOICE) -> str:
    """Gera áudio TTS e retorna o caminho do arquivo mp3 temporário."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    clean = _clean_for_tts(text) or "Sem texto para ler."
    communicate = edge_tts.Communicate(clean, voice, rate=TTS_RATE, pitch=TTS_PITCH)
    await communicate.save(tmp_path)
    return tmp_path


class TTSView(discord.ui.View):
    def __init__(self, text: str, voice: str = TTS_VOICE):
        super().__init__(timeout=120)
        self.text = text
        self.voice = voice

    @discord.ui.button(label="🔊 Ouvir", style=discord.ButtonStyle.secondary)
    async def ouvir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        tmp_path = None
        try:
            tmp_path = await _tts_to_file(self.text, self.voice)
            await interaction.followup.send(
                file=discord.File(tmp_path, filename="resposta.mp3"),
                ephemeral=True,
            )
        except Exception as e:
            log.error("Erro no TTS: %s", e)
            await interaction.followup.send(f"Erro ao gerar áudio: `{e}`", ephemeral=True)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


class ConfirmView(discord.ui.View):
    def __init__(self, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.confirmed: bool | None = None

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class AI(commands.Cog, name="IA"):
    """Assistente Gemini com ações no servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._history: dict[int, deque] = {}
        # rate limit: user_id -> list of timestamps
        self._rate: dict[int, list[float]] = {}
        # Canal da IA por servidor: guild_id -> channel_id (carregado do banco)
        self._guild_channels: dict[int, int] = {}
        # Tonalidade por servidor: guild_id -> chave de TONE_PRESETS
        self._guild_tones: dict[int, str] = {}
        # Voz por servidor: guild_id -> chave de VOICE_PRESETS
        self._guild_voices: dict[int, str] = {}
        self._db: aiosqlite.Connection | None = None

        if not GOOGLE_API_KEY:
            log.warning("GOOGLE_API_KEY não encontrada — cog de IA desativada.")
            self._client = None
            return

        self._client = genai.Client(api_key=GOOGLE_API_KEY)
        log.info("Cog IA carregada com modelo %s", MODEL_NAME)

    async def cog_load(self):
        # Banco de configuração por servidor (qual canal a IA escuta).
        self._db = await aiosqlite.connect(AI_DB_PATH)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS canais_ia (
                guild_id   INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS tons_ia (
                guild_id INTEGER PRIMARY KEY,
                tom      TEXT NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS vozes_ia (
                guild_id INTEGER PRIMARY KEY,
                voz      TEXT NOT NULL
            )
        """)
        await self._db.commit()
        # Carrega tudo pra memória (consulta a cada mensagem seria custosa).
        async with self._db.execute("SELECT guild_id, channel_id FROM canais_ia") as cur:
            async for guild_id, channel_id in cur:
                self._guild_channels[guild_id] = channel_id
        async with self._db.execute("SELECT guild_id, tom FROM tons_ia") as cur:
            async for guild_id, tom in cur:
                self._guild_tones[guild_id] = tom
        async with self._db.execute("SELECT guild_id, voz FROM vozes_ia") as cur:
            async for guild_id, voz in cur:
                self._guild_voices[guild_id] = voz
        log.info(
            "Config da IA carregada (%d canais, %d tons, %d vozes).",
            len(self._guild_channels), len(self._guild_tones), len(self._guild_voices),
        )

    async def cog_unload(self):
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ── Qual canal a IA escuta neste servidor ──────────────────────────────

    def _is_ai_channel(self, channel) -> bool:
        """Decide se a IA deve responder neste canal.
        Se o servidor configurou um canal específico (via !ia-canal), usa ele.
        Senão, cai no nome padrão global (AI_CHANNEL_NAME), tolerante a acento/caixa.
        """
        guild = getattr(channel, "guild", None)
        if guild is not None and guild.id in self._guild_channels:
            return channel.id == self._guild_channels[guild.id]
        nome = getattr(channel, "name", "") or ""
        return _norm_channel(nome) == _norm_channel(AI_CHANNEL_NAME)

    def _tone_for(self, guild_id: int | None) -> str:
        """Retorna a chave de tonalidade configurada para o servidor (ou o padrão)."""
        if guild_id is not None:
            return self._guild_tones.get(guild_id, DEFAULT_TONE)
        return DEFAULT_TONE

    def _voice_id_for(self, guild_id: int | None) -> str:
        """Retorna o id da voz TTS configurada para o servidor (ou o padrão)."""
        chave = self._guild_voices.get(guild_id, DEFAULT_VOICE) if guild_id is not None else DEFAULT_VOICE
        _, voice_id = VOICE_PRESETS.get(chave, VOICE_PRESETS[DEFAULT_VOICE])
        return voice_id

    # ── Rate limiting ──────────────────────────────────────────────────────

    def _check_rate(self, user_id: int) -> bool:
        """Retorna True se o usuário ainda está dentro do limite."""
        now = time.monotonic()
        timestamps = self._rate.setdefault(user_id, [])
        # Remove entradas fora da janela
        self._rate[user_id] = [t for t in timestamps if now - t < RATE_WINDOW]
        if len(self._rate[user_id]) >= RATE_LIMIT:
            return False
        self._rate[user_id].append(now)
        return True

    # ── API call com retry ─────────────────────────────────────────────────

    async def _generate_with_retry(self, contents: list, max_retries: int = 3, system_instruction: str | None = None):
        """Chama o Gemini com retry exponencial em erros transitórios (503/429/overload)."""
        config = types.GenerateContentConfig(
            tools=TOOLS,
            system_instruction=system_instruction or _build_system_prompt(DEFAULT_TONE),
            temperature=0.9,
        )
        delay = 1.0
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await self._client.aio.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                msg = str(e).lower()
                # Cota diária esgotada: tentar de novo não adianta, sobe na hora.
                if _is_daily_quota(msg):
                    raise
                transient = any(
                    s in msg for s in ("503", "429", "unavailable", "overload", "high demand", "try again")
                )
                if not transient or attempt == max_retries - 1:
                    raise
                last_exc = e
                log.warning("Erro transitório do Gemini (tentativa %d/%d): %s", attempt + 1, max_retries, e)
                await asyncio.sleep(delay)
                delay *= 2
        raise last_exc  # nunca alcançado, mas explícito

    # ── History helpers ────────────────────────────────────────────────────

    def _get_history(self, channel_id: int) -> deque:
        if channel_id not in self._history:
            self._history[channel_id] = deque(maxlen=MAX_HISTORY)
        return self._history[channel_id]

    def _build_contents(self, channel_id: int, new_message: str) -> list:
        history = self._get_history(channel_id)
        contents = []
        for role, text in history:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=new_message)]))
        return contents

    # ── Tool execution ─────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict, message: discord.Message) -> str:
        guild = message.guild
        author = message.author
        ctx = await self.bot.get_context(message)
        music_cog = self.bot.cogs.get("Música")

        try:
            # --- Música ---
            if name == "tocar_musica":
                if not music_cog:
                    return "Cog de música não carregada."
                if not author.voice:
                    return "O usuário não está em nenhum canal de voz."
                query = args.get("query", "")
                await music_cog.play(ctx, query=query)
                return f"Buscando e tocando: {query}"

            elif name == "entrar_sala_voz":
                nome_sala = args.get("nome_sala", "")
                canal = discord.utils.get(guild.voice_channels, name=nome_sala)
                if not canal:
                    return f"Canal de voz '{nome_sala}' não encontrado."
                if guild.voice_client:
                    await guild.voice_client.move_to(canal)
                else:
                    await canal.connect()
                return f"Entrei na sala '{canal.name}'."

            elif name == "sair_sala_voz":
                if guild.voice_client:
                    await guild.voice_client.disconnect()
                    return "Saí da sala de voz."
                return "Não estou em nenhuma sala de voz."

            elif name == "pular_musica":
                if guild.voice_client and guild.voice_client.is_playing():
                    guild.voice_client.stop()
                    return "Música pulada!"
                return "Nenhuma música tocando."

            elif name == "parar_musica":
                if music_cog:
                    state = music_cog._state(guild.id)
                    state.queue.clear()
                    state.current = None
                if guild.voice_client:
                    await guild.voice_client.disconnect()
                return "Música parada e fila limpa."

            elif name == "ver_fila":
                if not music_cog:
                    return "Cog de música não carregada."
                state = music_cog._state(guild.id)
                if not state.current and not state.queue:
                    return "Fila vazia."
                items = []
                if state.current:
                    items.append(f"Tocando: {state.current['title']}")
                for i, s in enumerate(state.queue[:10], 1):
                    items.append(f"{i}. {s['title']}")
                if len(state.queue) > 10:
                    items.append(f"...e mais {len(state.queue) - 10}")
                return "\n".join(items)

            # --- Canais ---
            elif name == "criar_canal":
                if not author.guild_permissions.manage_channels:
                    return "Você não tem permissão para criar canais."
                nome = args.get("nome", "")
                tipo = args.get("tipo", "texto")
                categoria_nome = args.get("categoria")
                # Evita duplicatas: se já existe um canal com esse nome, não cria de novo.
                existente = discord.utils.find(
                    lambda c: _norm_channel(c.name) == _norm_channel(nome),
                    guild.channels,
                )
                if existente:
                    return f"O canal '{existente.name}' já existe — não criei outro."
                categoria = discord.utils.get(guild.categories, name=categoria_nome) if categoria_nome else None
                if tipo == "voz":
                    canal = await guild.create_voice_channel(nome, category=categoria)
                else:
                    canal = await guild.create_text_channel(nome, category=categoria)
                return f"Canal '{canal.name}' criado!"

            elif name == "publicar_em_canal":
                if not author.guild_permissions.manage_messages:
                    return "Você não tem permissão para publicar em canais."
                nome = args.get("canal", "")
                conteudo = args.get("mensagem", "")
                if not conteudo.strip():
                    return "Não há mensagem para publicar."
                alvo = _norm_channel(nome)
                canais_texto = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
                # 1) match exato (sem acento); 2) fallback: começa com / contém o nome pedido.
                canal = (
                    discord.utils.find(lambda c: _norm_channel(c.name) == alvo, canais_texto)
                    or discord.utils.find(lambda c: _norm_channel(c.name).startswith(alvo), canais_texto)
                    or discord.utils.find(lambda c: alvo in _norm_channel(c.name), canais_texto)
                )
                if not canal:
                    disponiveis = ", ".join(f"#{c.name}" for c in canais_texto[:15]) or "(nenhum)"
                    return (
                        f"Canal de texto '{nome}' não encontrado — NÃO publiquei nada. "
                        f"Canais disponíveis: {disponiveis}. "
                        f"Avise o usuário com sinceridade que o canal não existe; não diga que publicou."
                    )
                for chunk in (conteudo[i:i + 2000] for i in range(0, len(conteudo), 2000)):
                    await canal.send(chunk)
                return f"Mensagem publicada no canal #{canal.name}."

            elif name == "deletar_canal":
                if not author.guild_permissions.manage_channels:
                    return "Você não tem permissão para deletar canais."
                nome = args.get("nome", "")
                canal = discord.utils.get(guild.channels, name=nome)
                if not canal:
                    return f"Canal '{nome}' não encontrado."
                await canal.delete()
                return f"Canal '{nome}' deletado."

            # --- Moderação ---
            elif name == "kick_membro":
                if not author.guild_permissions.kick_members:
                    return "Você não tem permissão para expulsar membros."
                nome = args.get("membro", "")
                motivo = args.get("motivo", "Solicitado via IA")
                membro = discord.utils.find(
                    lambda m: m.name.lower() == nome.lower() or m.display_name.lower() == nome.lower(),
                    guild.members
                )
                if not membro:
                    return f"Membro '{nome}' não encontrado."
                await membro.kick(reason=motivo)
                return f"{membro.display_name} foi expulso. Motivo: {motivo}"

            elif name == "ban_membro":
                if not author.guild_permissions.ban_members:
                    return "Você não tem permissão para banir membros."
                nome = args.get("membro", "")
                motivo = args.get("motivo", "Solicitado via IA")
                membro = discord.utils.find(
                    lambda m: m.name.lower() == nome.lower() or m.display_name.lower() == nome.lower(),
                    guild.members
                )
                if not membro:
                    return f"Membro '{nome}' não encontrado."
                await membro.ban(reason=motivo)
                return f"{membro.display_name} foi banido. Motivo: {motivo}"

            elif name == "mutar_membro":
                if not author.guild_permissions.manage_roles:
                    return "Você não tem permissão para silenciar membros."
                nome = args.get("membro", "")
                motivo = args.get("motivo", "Solicitado via IA")
                membro = discord.utils.find(
                    lambda m: m.name.lower() == nome.lower() or m.display_name.lower() == nome.lower(),
                    guild.members
                )
                if not membro:
                    return f"Membro '{nome}' não encontrado."
                muted_role = discord.utils.get(guild.roles, name="Muted")
                if not muted_role:
                    muted_role = await guild.create_role(name="Muted")
                    for channel in guild.channels:
                        await channel.set_permissions(muted_role, send_messages=False, speak=False)
                if muted_role in membro.roles:
                    return f"{membro.display_name} já está silenciado."
                await membro.add_roles(muted_role, reason=motivo)
                return f"{membro.display_name} foi silenciado. Motivo: {motivo}"

            elif name == "desmutar_membro":
                if not author.guild_permissions.manage_roles:
                    return "Você não tem permissão para remover silêncio de membros."
                nome = args.get("membro", "")
                membro = discord.utils.find(
                    lambda m: m.name.lower() == nome.lower() or m.display_name.lower() == nome.lower(),
                    guild.members
                )
                if not membro:
                    return f"Membro '{nome}' não encontrado."
                muted_role = discord.utils.get(guild.roles, name="Muted")
                if not muted_role or muted_role not in membro.roles:
                    return f"{membro.display_name} não está silenciado."
                await membro.remove_roles(muted_role)
                return f"Silêncio de {membro.display_name} removido."

            elif name == "desbanir_membro":
                if not author.guild_permissions.ban_members:
                    return "Você não tem permissão para remover bans."
                identificador = args.get("identificador", "").strip()
                bans = [entry async for entry in guild.bans()]
                user = None
                if identificador.isdigit():
                    user = next((e.user for e in bans if e.user.id == int(identificador)), None)
                else:
                    nome, _, disc = identificador.partition("#")
                    user = next(
                        (e.user for e in bans if e.user.name == nome and (not disc or e.user.discriminator == disc)),
                        None,
                    )
                if not user:
                    return f"Usuário '{identificador}' não encontrado na lista de bans."
                await guild.unban(user)
                return f"Ban de {user} removido com sucesso."

            # --- Info ---
            elif name == "listar_canais":
                texto = [f"#{c.name}" for c in guild.text_channels]
                voz = [f"🔊 {c.name}" for c in guild.voice_channels]
                return "Texto: " + ", ".join(texto) + " | Voz: " + ", ".join(voz)

            elif name == "listar_membros_online":
                online = [
                    m.display_name for m in guild.members
                    if m.status != discord.Status.offline and not m.bot
                ]
                return f"Online ({len(online)}): {', '.join(online)}" if online else "Ninguém online."

            return f"Ferramenta '{name}' não reconhecida."

        except Exception as e:
            log.error("Erro ao executar ferramenta '%s': %s", name, e)
            return f"Erro ao executar '{name}': {e}"

    async def _confirm_destructive(self, message: discord.Message, name: str, args: dict) -> bool:
        """Pede confirmação antes de ações destrutivas. Retorna True se confirmado."""
        labels = {
            "kick_membro":    f"⚠️ Expulsar **{args.get('membro', '?')}**?",
            "ban_membro":     f"⚠️ Banir **{args.get('membro', '?')}**?",
            "desbanir_membro":f"⚠️ Remover o ban de **{args.get('identificador', '?')}**?",
            "desmutar_membro":f"⚠️ Remover o mute de **{args.get('membro', '?')}**?",
            "deletar_canal":  f"⚠️ Deletar o canal **#{args.get('nome', '?')}**?",
        }
        desc = labels.get(name, "Confirmar ação?")
        motivo = args.get("motivo", "Solicitado via IA")
        embed = discord.Embed(
            title="Confirmação necessária",
            description=f"{desc}\n**Motivo:** {motivo}",
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Expira em 30 segundos.")
        view = ConfirmView()
        msg = await message.channel.send(embed=embed, view=view)
        await view.wait()
        await msg.delete()
        return view.confirmed is True

    # ── Main listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return  # IA só funciona em servidores, não em DMs
        if not self._is_ai_channel(message.channel):
            return
        if message.content.startswith(self.bot.command_prefix):
            return
        if not self._client:
            await message.channel.send("⚠️ GOOGLE_API_KEY não configurada.")
            return

        # Blacklist check
        blacklist = getattr(self.bot, "blacklist", set())
        if message.author.id in blacklist:
            return

        # Rate limit
        if not self._check_rate(message.author.id):
            await message.channel.send(
                f"{message.author.mention} devagar aí 😅 — máximo {RATE_LIMIT} mensagens por minuto.",
                delete_after=10,
            )
            return

        user_input = message.content.strip()
        if not user_input:
            return

        # Trunca entradas muito longas
        if len(user_input) > MAX_INPUT_LEN:
            user_input = user_input[:MAX_INPUT_LEN] + "…"

        # Detecção de prompt injection
        if _INJECTION_PATTERNS.search(user_input):
            await message.channel.send("🚫 Parece que você tá tentando me reprogramar, né? Não vai rolar. 😄")
            return

        # Tonalidade configurada para este servidor
        system_prompt = _build_system_prompt(self._tone_for(message.guild.id))

        async with message.channel.typing():
            try:
                contents = self._build_contents(message.channel.id, user_input)
                reply = ""

                for _ in range(10):
                    response = await self._generate_with_retry(contents, system_instruction=system_prompt)

                    candidate = response.candidates[0]
                    parts = candidate.content.parts
                    function_calls = [p for p in parts if p.function_call]

                    if not function_calls:
                        text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                        reply = "\n".join(text_parts)
                        break

                    contents.append(candidate.content)
                    tool_results = []
                    for part in function_calls:
                        fc = part.function_call
                        fc_args = dict(fc.args) if fc.args else {}

                        # Confirmação para ações destrutivas
                        if fc.name in _DESTRUCTIVE:
                            confirmed = await self._confirm_destructive(message, fc.name, fc_args)
                            if not confirmed:
                                result = "Ação cancelada pelo usuário."
                                log.info("Ferramenta '%s' cancelada pelo usuário.", fc.name)
                                tool_results.append(types.Part(
                                    function_response=types.FunctionResponse(
                                        name=fc.name,
                                        response={"result": result}
                                    )
                                ))
                                continue

                        result = await self._execute_tool(fc.name, fc_args, message)
                        log.info("Ferramenta '%s' executada: %s", fc.name, result)
                        tool_results.append(types.Part(
                            function_response=types.FunctionResponse(
                                name=fc.name,
                                response={"result": result}
                            )
                        ))

                    contents.append(types.Content(role="user", parts=tool_results))

                # Salva no histórico
                history = self._get_history(message.channel.id)
                history.append(("user", user_input))
                if reply:
                    history.append(("model", reply))

                if reply:
                    voz = self._voice_id_for(message.guild.id)
                    chunks = [reply[i:i + 2000] for i in range(0, len(reply), 2000)]
                    for i, chunk in enumerate(chunks):
                        # Botão de áudio só na última parte
                        view = TTSView(reply, voice=voz) if i == len(chunks) - 1 else discord.utils.MISSING
                        await message.channel.send(chunk, view=view)

            except Exception as e:
                log.error("Erro na API do Gemini: %s", e)
                await message.channel.send(_friendly_error(e))

    @commands.command(name="ia-limpar", aliases=["ai-clear"])
    @commands.has_permissions(manage_messages=True)
    async def clear_history(self, ctx: commands.Context):
        """Limpa o histórico de conversa do canal."""
        self._history.pop(ctx.channel.id, None)
        await ctx.send("🧹 Histórico limpo!")

    @commands.command(name="ia-canal", aliases=["ai-channel"])
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def set_ai_channel(self, ctx: commands.Context, canal: discord.TextChannel = None):
        """Define em qual canal de texto a IA vai responder neste servidor."""
        if canal is None:
            # Mostra a configuração atual.
            atual_id = self._guild_channels.get(ctx.guild.id)
            if atual_id:
                ch = ctx.guild.get_channel(atual_id)
                onde = ch.mention if ch else f"(canal apagado — id {atual_id})"
                desc = f"A IA está respondendo em {onde}."
            else:
                desc = f"A IA está usando o canal padrão: **#{AI_CHANNEL_NAME}** (nenhum canal personalizado definido)."
            desc += "\n\nPara mudar, use `!ia-canal #canal`.\nPara voltar ao padrão, use `!ia-canal-padrao`."
            return await ctx.send(embed=discord.Embed(
                title="Canal da IA", description=desc, color=discord.Color.blurple()
            ))

        if self._db is None:
            return await ctx.send("⚠️ Configuração indisponível no momento.")

        await self._db.execute(
            "INSERT INTO canais_ia (guild_id, channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            (ctx.guild.id, canal.id),
        )
        await self._db.commit()
        self._guild_channels[ctx.guild.id] = canal.id
        await ctx.send(embed=discord.Embed(
            title="✅ Canal da IA definido",
            description=f"A partir de agora, a IA responde em {canal.mention}.\n"
                        f"É só mandar mensagens lá — sem precisar de comando.",
            color=discord.Color.green(),
        ))

    @commands.command(name="ia-canal-padrao", aliases=["ai-channel-reset"])
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def reset_ai_channel(self, ctx: commands.Context):
        """Volta a IA para o canal padrão (remove a configuração personalizada)."""
        if self._db is None:
            return await ctx.send("⚠️ Configuração indisponível no momento.")
        await self._db.execute("DELETE FROM canais_ia WHERE guild_id = ?", (ctx.guild.id,))
        await self._db.commit()
        self._guild_channels.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(
            title="🔄 Canal da IA resetado",
            description=f"A IA voltou a usar o canal padrão **#{AI_CHANNEL_NAME}**.",
            color=discord.Color.orange(),
        ))

    @commands.command(name="ia-tom", aliases=["ai-tone", "ia-tonalidade"])
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def set_ai_tone(self, ctx: commands.Context, tom: str = None):
        """Escolhe a tonalidade com que a IA responde neste servidor."""
        opcoes = "\n".join(f"• `{chave}` — {rotulo}" for chave, (rotulo, _) in TONE_PRESETS.items())

        # Sem argumento: mostra o tom atual e as opções.
        if tom is None:
            atual = self._tone_for(ctx.guild.id)
            rotulo_atual = TONE_PRESETS[atual][0]
            return await ctx.send(embed=discord.Embed(
                title="🎭 Tonalidade da IA",
                description=(
                    f"Tom atual: **{rotulo_atual}** (`{atual}`)\n\n"
                    f"**Opções disponíveis:**\n{opcoes}\n\n"
                    f"Para mudar: `!ia-tom <opção>` (ex: `!ia-tom formal`)."
                ),
                color=discord.Color.blurple(),
            ))

        tom = tom.lower().strip()
        if tom not in TONE_PRESETS:
            return await ctx.send(embed=discord.Embed(
                title="Tom inválido",
                description=f"'{tom}' não existe.\n\n**Opções disponíveis:**\n{opcoes}",
                color=discord.Color.red(),
            ))

        if self._db is None:
            return await ctx.send("⚠️ Configuração indisponível no momento.")

        await self._db.execute(
            "INSERT INTO tons_ia (guild_id, tom) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET tom = excluded.tom",
            (ctx.guild.id, tom),
        )
        await self._db.commit()
        self._guild_tones[ctx.guild.id] = tom
        rotulo = TONE_PRESETS[tom][0]
        await ctx.send(embed=discord.Embed(
            title="✅ Tonalidade alterada",
            description=f"Agora vou responder no tom **{rotulo}**. Isso também vale para o áudio do botão 🔊 Ouvir.",
            color=discord.Color.green(),
        ))

    @commands.command(name="ia-voz", aliases=["ai-voice"])
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def set_ai_voice(self, ctx: commands.Context, voz: str = None):
        """Escolhe a voz do áudio (botão 🔊 Ouvir) neste servidor."""
        opcoes = "\n".join(f"• `{chave}` — {rotulo}" for chave, (rotulo, _) in VOICE_PRESETS.items())

        if voz is None:
            atual = self._guild_voices.get(ctx.guild.id, DEFAULT_VOICE)
            rotulo_atual = VOICE_PRESETS[atual][0]
            return await ctx.send(embed=discord.Embed(
                title="🎙️ Voz da IA",
                description=(
                    f"Voz atual: **{rotulo_atual}** (`{atual}`)\n\n"
                    f"**Vozes disponíveis:**\n{opcoes}\n\n"
                    f"Para mudar: `!ia-voz <opção>` (ex: `!ia-voz antonio`)."
                ),
                color=discord.Color.blurple(),
            ))

        voz = voz.lower().strip()
        if voz not in VOICE_PRESETS:
            return await ctx.send(embed=discord.Embed(
                title="Voz inválida",
                description=f"'{voz}' não existe.\n\n**Vozes disponíveis:**\n{opcoes}",
                color=discord.Color.red(),
            ))

        if self._db is None:
            return await ctx.send("⚠️ Configuração indisponível no momento.")

        await self._db.execute(
            "INSERT INTO vozes_ia (guild_id, voz) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET voz = excluded.voz",
            (ctx.guild.id, voz),
        )
        await self._db.commit()
        self._guild_voices[ctx.guild.id] = voz
        rotulo = VOICE_PRESETS[voz][0]
        await ctx.send(embed=discord.Embed(
            title="✅ Voz alterada",
            description=f"A voz do áudio agora é **{rotulo}**. Clique em 🔊 Ouvir numa resposta pra testar!",
            color=discord.Color.green(),
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
