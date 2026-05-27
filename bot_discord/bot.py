import os
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
    "cogs.music",
    "cogs.moderation",
    "cogs.utility",
    "cogs.playlist",
    "cogs.ai",
]


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

    async def setup_hook(self):
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
        else:
            log.error("Erro no comando '%s': %s", ctx.command, error)
            await ctx.send(
                embed=discord.Embed(
                    description=f"Ocorreu um erro inesperado: `{error}`",
                    color=discord.Color.red(),
                )
            )


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
