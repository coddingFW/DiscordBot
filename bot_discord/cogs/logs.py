import asyncio
import logging
import discord
from discord.ext import commands

log = logging.getLogger("cog.logs")

LOG_CHANNEL = "logs"


def log_embed(titulo: str, cor: discord.Color, **fields) -> discord.Embed:
    embed = discord.Embed(title=titulo, color=cor)
    for name, value in fields.items():
        embed.add_field(name=name, value=value, inline=True)
    return embed


async def send_log(guild: discord.Guild, embed: discord.Embed):
    canal = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if canal:
        try:
            await canal.send(embed=embed)
        except discord.Forbidden:
            pass


class Logs(commands.Cog, name="Logs"):
    """Registra eventos de moderação no canal #logs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        moderador = "Desconhecido"
        motivo = "Sem motivo"
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                moderador = str(entry.user)
                motivo = entry.reason or "Sem motivo"
                break
        await send_log(guild, log_embed(
            "🔨 Membro Banido", discord.Color.red(),
            Usuário=f"{user} ({user.id})",
            Moderador=moderador,
            Motivo=motivo,
        ))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        moderador = "Desconhecido"
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.target.id == user.id:
                moderador = str(entry.user)
                break
        await send_log(guild, log_embed(
            "✅ Ban Removido", discord.Color.green(),
            Usuário=f"{user} ({user.id})",
            Moderador=moderador,
        ))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await asyncio.sleep(1)
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                await send_log(member.guild, log_embed(
                    "👢 Membro Expulso", discord.Color.orange(),
                    Usuário=f"{member} ({member.id})",
                    Moderador=str(entry.user),
                    Motivo=entry.reason or "Sem motivo",
                ))
                return

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await send_log(member.guild, log_embed(
            "📥 Novo Membro", discord.Color.blurple(),
            Usuário=f"{member} ({member.id})",
            Conta=f"<t:{int(member.created_at.timestamp())}:R>",
        ))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.content:
            return
        await send_log(message.guild, log_embed(
            "🗑️ Mensagem Deletada", discord.Color.dark_gray(),
            Autor=f"{message.author} ({message.author.id})",
            Canal=f"#{message.channel.name}",
            Conteúdo=message.content[:500] or "*(sem texto)*",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
