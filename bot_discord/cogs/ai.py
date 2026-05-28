import os
import time
import logging
import re
from collections import deque
import discord
from discord.ext import commands
from google import genai
from google.genai import types

log = logging.getLogger("cog.ai")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_CHANNEL_NAME = os.getenv("AI_CHANNEL_NAME", "ia")
MODEL_NAME = "gemini-2.5-flash"
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

SYSTEM_PROMPT = """Você é o Good Vibes, assistente do servidor Discord.
Fale sempre de forma informal, descontraída, como papo entre amigos.
Use gírias brasileiras, emojis quando fizer sentido, mas sem exagerar.
Respostas curtas — ninguém quer textão.
Se o papo for engraçado, entra na brincadeira.
Responda sempre em português do Brasil.

Você foi criado por coddingFW. Se alguém perguntar quem te criou ou te desenvolveu, fala que foi o coddingFW e manda o perfil dele no GitHub: https://github.com/coddingFW

Você tem ferramentas para agir no servidor. Quando o usuário pedir algo que envolva música, canais ou moderação, USE as ferramentas — não explique como fazer, FAÇA."""

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
_DESTRUCTIVE = {"kick_membro", "ban_membro", "deletar_canal"}


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

        if not GOOGLE_API_KEY:
            log.warning("GOOGLE_API_KEY não encontrada — cog de IA desativada.")
            self._client = None
            return

        self._client = genai.Client(api_key=GOOGLE_API_KEY)
        log.info("Cog IA carregada com modelo %s", MODEL_NAME)

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
                categoria = discord.utils.get(guild.categories, name=categoria_nome) if categoria_nome else None
                if tipo == "voz":
                    canal = await guild.create_voice_channel(nome, category=categoria)
                else:
                    canal = await guild.create_text_channel(nome, category=categoria)
                return f"Canal '{canal.name}' criado!"

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
            "kick_membro": f"⚠️ Expulsar **{args.get('membro', '?')}**?",
            "ban_membro": f"⚠️ Banir **{args.get('membro', '?')}**?",
            "deletar_canal": f"⚠️ Deletar o canal **#{args.get('nome', '?')}**?",
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
        if message.channel.name != AI_CHANNEL_NAME:
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

        async with message.channel.typing():
            try:
                contents = self._build_contents(message.channel.id, user_input)
                reply = ""

                for _ in range(10):
                    response = await self._client.aio.models.generate_content(
                        model=MODEL_NAME,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            tools=TOOLS,
                            system_instruction=SYSTEM_PROMPT,
                            temperature=0.9,
                        )
                    )

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
                    for i in range(0, len(reply), 2000):
                        await message.channel.send(reply[i:i + 2000])

            except Exception as e:
                log.error("Erro na API do Gemini: %s", e)
                await message.channel.send(f"Ih, deu ruim aqui 😅 — `{e}`")

    @commands.command(name="ia-limpar", aliases=["ai-clear"])
    @commands.has_permissions(manage_messages=True)
    async def clear_history(self, ctx: commands.Context):
        """Limpa o histórico de conversa do canal."""
        self._history.pop(ctx.channel.id, None)
        await ctx.send("🧹 Histórico limpo!")


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
