import os
import json
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

COGS = [
    "cogs.logs",
    "cogs.music",
    "cogs.moderation",
    "cogs.warns",
    "cogs.utility",
    "cogs.playlist",
    "cogs.ai",
]

BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), "blacklist.json")


def _load_blacklist() -> set[int]:
    if not os.path.exists(BLACKLIST_FILE):
        return set()
    with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_blacklist(bl: set[int]):
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(list(bl), f)


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=os.getenv("BOT_PREFIX", "!"),
            intents=intents,
            help_command=commands.DefaultHelpCommand(dm_help=True),
            description="Bot multifuncional com música, moderação e utilitários.",
        )
        self.blacklist: set[int] = _load_blacklist()

    async def setup_hook(self):
        self.add_command(blacklist_add)
        self.add_command(blacklist_remove)
        self.add_command(blacklist_ver)
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Cog carregada: %s", cog)
            except Exception as exc:
                log.error("Falha ao carregar %s: %s", cog, exc)

    async def on_ready(self):
        # Limpa sessões de voz antigas para evitar erro 4017
        for guild in self.guilds:
            await guild.change_voice_state(channel=None)

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{self.command_prefix}help",
            )
        )
        log.info("Bot online: %s (ID: %s)", self.user.name, self.user.id)
        log.info("Servidores: %d | Prefixo: %s", len(self.guilds), self.command_prefix)

    async def on_guild_join(self, guild: discord.Guild):
        log.info("Adicionado ao servidor: %s (ID: %s) — Total: %d servidores",
                 guild.name, guild.id, len(self.guilds))

        # Encontra o primeiro canal de texto onde o bot pode enviar mensagens
        canal = next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
            None
        )
        if not canal:
            return

        prefix = self.command_prefix
        embed = discord.Embed(
            title="👋 Olá! Eu sou o Good Vibes",
            description="Obrigado por me adicionar! Aqui vai um resumo do que eu faço:",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="🎵 Música", value=(
            f"`{prefix}m <música>` — toca uma música do YouTube\n"
            f"`{prefix}skip` — pula a música\n"
            f"`{prefix}queue` — ver a fila\n"
            f"`{prefix}stop` — para e desconecta\n"
            f"`{prefix}volume <0-100>` — ajusta o volume"
        ), inline=False)
        embed.add_field(name="🛡️ Moderação", value=(
            f"`{prefix}kick @membro` — expulsa\n"
            f"`{prefix}ban @membro` — bane\n"
            f"`{prefix}purge <n>` — apaga mensagens\n"
            f"`{prefix}mute @membro` — silencia\n"
            f"`{prefix}warn @membro <motivo>` — aviso com histórico (auto-mute em 3, auto-ban em 5)\n"
            f"`{prefix}warns @membro` — ver histórico de avisos\n"
            f"`{prefix}clearwarns @membro` — limpar todos os avisos"
        ), inline=False)
        embed.add_field(name="🎶 Playlists", value=(
            f"`{prefix}playlist criar <nome>` — cria playlist\n"
            f"`{prefix}playlist add <nome> <música>` — adiciona música\n"
            f"`{prefix}playlist tocar <nome>` — toca toda a playlist"
        ), inline=False)
        embed.add_field(name="🤖 Assistente IA", value=(
            "Crie um canal chamado `ia` e converse comigo livremente!\n"
            "Posso tocar músicas, criar canais e muito mais só de pedir."
        ), inline=False)
        embed.add_field(name="🔧 Utilitários", value=(
            f"`{prefix}botinfo` — info do bot\n"
            f"`{prefix}serverinfo` — info do servidor\n"
            f"`{prefix}userinfo @membro` — info de um usuário\n"
            f"`{prefix}ping` — latência"
        ), inline=False)
        embed.set_footer(text=f"Use {prefix}help para ver todos os comandos disponíveis.")
        embed.set_thumbnail(url=self.user.display_avatar.url)

        await canal.send(embed=embed)

    async def on_guild_remove(self, guild: discord.Guild):
        log.info("Removido do servidor: %s (ID: %s) — Total: %d servidores",
                 guild.name, guild.id, len(self.guilds))

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=discord.Embed(
                    description=f"Argumento ausente: `{error.param.name}`.\nUse `{self.command_prefix}help {ctx.command}` para ver o uso correto.",
                    color=discord.Color.orange(),
                )
            )
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description="Você não tem permissão para usar este comando.",
                    color=discord.Color.red(),
                )
            )
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description="Eu não tenho permissão para executar esta ação.",
                    color=discord.Color.red(),
                )
            )
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                embed=discord.Embed(
                    description=f"⏳ Calma aí! Espera **{error.retry_after:.0f}s** antes de usar `{ctx.command}` de novo.",
                    color=discord.Color.orange(),
                )
            )
        elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            await ctx.send(
                embed=discord.Embed(
                    description=f"Argumento inválido. Use `{self.command_prefix}help {ctx.command}` para ver o uso correto.",
                    color=discord.Color.orange(),
                )
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send(
                embed=discord.Embed(
                    description="Este comando só funciona dentro de um servidor.",
                    color=discord.Color.orange(),
                )
            )
        elif isinstance(error, commands.NotOwner):
            await ctx.send(
                embed=discord.Embed(
                    description="Só o dono do bot pode usar este comando.",
                    color=discord.Color.red(),
                )
            )
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(
                embed=discord.Embed(
                    description="Você não pode usar este comando aqui.",
                    color=discord.Color.red(),
                )
            )
        else:
            # Erro inesperado: loga o detalhe técnico, mas mostra mensagem clara.
            log.error("Erro no comando '%s': %s", ctx.command, error)
            await ctx.send(
                embed=discord.Embed(
                    description=(
                        "💥 **Ops, algo deu errado ao executar esse comando.**\n"
                        "Não é culpa sua — tenta de novo daqui a pouco. "
                        "Se continuar, avisa quem cuida do bot."
                    ),
                    color=discord.Color.red(),
                )
            )


@commands.command(name="blacklist-add", aliases=["bl-add"])
@commands.is_owner()
async def blacklist_add(ctx: commands.Context, user: discord.User):
    """(Dono) Adiciona um usuário à blacklist da IA."""
    ctx.bot.blacklist.add(user.id)
    _save_blacklist(ctx.bot.blacklist)
    await ctx.send(f"✅ **{user}** adicionado à blacklist.")


@commands.command(name="blacklist-remove", aliases=["bl-remove"])
@commands.is_owner()
async def blacklist_remove(ctx: commands.Context, user: discord.User):
    """(Dono) Remove um usuário da blacklist da IA."""
    ctx.bot.blacklist.discard(user.id)
    _save_blacklist(ctx.bot.blacklist)
    await ctx.send(f"✅ **{user}** removido da blacklist.")


@commands.command(name="blacklist-ver", aliases=["bl-list"])
@commands.is_owner()
async def blacklist_ver(ctx: commands.Context):
    """(Dono) Lista usuários na blacklist."""
    if not ctx.bot.blacklist:
        return await ctx.send("Blacklist vazia.")
    lines = [f"<@{uid}> ({uid})" for uid in ctx.bot.blacklist]
    await ctx.send("**Blacklist:**\n" + "\n".join(lines))


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.critical("DISCORD_TOKEN não encontrado. Crie um arquivo .env com o token.")
        return

    bot = DiscordBot()
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        log.critical("Token inválido. Gere um novo no Discord Developer Portal.")
    except Exception as exc:
        log.critical("Erro ao iniciar o bot: %s", exc)


if __name__ == "__main__":
    main()
