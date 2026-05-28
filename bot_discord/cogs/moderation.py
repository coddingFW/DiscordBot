import logging
import discord
from discord.ext import commands
from .logs import send_log, log_embed

log = logging.getLogger("cog.moderation")


def mod_embed(title: str, description: str, color=discord.Color.red()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Moderation(commands.Cog, name="Moderação"):
    """Comandos de moderação do servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="kick", help="Expulsa um membro do servidor.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sem motivo"):
        await member.kick(reason=reason)
        await ctx.send(
            embed=mod_embed(
                "Membro Expulso",
                f"{member.mention} foi expulso.\n**Motivo:** {reason}",
                discord.Color.orange(),
            )
        )
        await send_log(ctx.guild, log_embed(
            "👢 Membro Expulso (comando)", discord.Color.orange(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s expulsou %s. Motivo: %s", ctx.author, member, reason)

    @commands.command(name="ban", help="Bane um membro do servidor.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sem motivo"):
        await member.ban(reason=reason)
        await ctx.send(
            embed=mod_embed(
                "Membro Banido",
                f"{member.mention} foi banido.\n**Motivo:** {reason}",
            )
        )
        await send_log(ctx.guild, log_embed(
            "🔨 Membro Banido (comando)", discord.Color.red(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s baniu %s. Motivo: %s", ctx.author, member, reason)

    @commands.command(name="unban", help="Remove o ban de um usuário (Nome#0000 ou ID).")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, *, identifier: str):
        bans = [entry async for entry in ctx.guild.bans()]

        user = None
        if identifier.isdigit():
            user = next((e.user for e in bans if e.user.id == int(identifier)), None)
        else:
            name, _, disc = identifier.partition("#")
            user = next(
                (e.user for e in bans if e.user.name == name and (not disc or e.user.discriminator == disc)),
                None,
            )

        if user is None:
            return await ctx.send(embed=mod_embed("Erro", "Usuário não encontrado na lista de bans.", discord.Color.orange()))

        await ctx.guild.unban(user)
        await ctx.send(embed=mod_embed("Desbanido", f"**{user}** foi desbanido.", discord.Color.green()))
        await send_log(ctx.guild, log_embed(
            "✅ Ban Removido (comando)", discord.Color.green(),
            Usuário=f"{user} ({user.id})",
            Moderador=str(ctx.author),
        ))
        log.info("%s desbaniu %s", ctx.author, user)

    @commands.command(name="purge", help="Apaga mensagens do canal (máx. 100).")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def purge(self, ctx: commands.Context, amount: int):
        if not 1 <= amount <= 100:
            return await ctx.send(embed=mod_embed("Erro", "Informe um número entre 1 e 100.", discord.Color.orange()))
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(
            embed=mod_embed("Mensagens Apagadas", f"{len(deleted) - 1} mensagens removidas.", discord.Color.orange())
        )
        await msg.delete(delay=5)

    @commands.command(name="mute", help="Silencia um membro (requer cargo 'Muted').")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sem motivo"):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role is None:
            muted_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False)

        if muted_role in member.roles:
            return await ctx.send(embed=mod_embed("Aviso", f"{member.mention} já está silenciado.", discord.Color.orange()))

        await member.add_roles(muted_role, reason=reason)
        await ctx.send(embed=mod_embed("Silenciado", f"{member.mention} foi silenciado.\n**Motivo:** {reason}"))
        await send_log(ctx.guild, log_embed(
            "🔇 Membro Silenciado", discord.Color.dark_gray(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s silenciou %s. Motivo: %s", ctx.author, member, reason)

    @commands.command(name="unmute", help="Remove o silêncio de um membro.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role is None or muted_role not in member.roles:
            return await ctx.send(embed=mod_embed("Aviso", f"{member.mention} não está silenciado.", discord.Color.orange()))

        await member.remove_roles(muted_role)
        await ctx.send(embed=mod_embed("Voz Restaurada", f"{member.mention} pode falar novamente.", discord.Color.green()))
        await send_log(ctx.guild, log_embed(
            "🔊 Mute Removido", discord.Color.green(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
        ))
        log.info("%s removeu mute de %s", ctx.author, member)

    @commands.command(name="warn", help="Avisa um membro por mensagem direta.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        try:
            await member.send(
                embed=discord.Embed(
                    title=f"Aviso em {ctx.guild.name}",
                    description=f"Você recebeu um aviso.\n**Motivo:** {reason}",
                    color=discord.Color.orange(),
                )
            )
            sent = True
        except discord.Forbidden:
            sent = False

        dm_status = "" if sent else "\n*(Não foi possível enviar DM ao usuário)*"
        await ctx.send(
            embed=mod_embed(
                "Aviso Enviado",
                f"{member.mention} foi avisado.\n**Motivo:** {reason}{dm_status}",
                discord.Color.orange(),
            )
        )
        await send_log(ctx.guild, log_embed(
            "⚠️ Aviso Emitido", discord.Color.orange(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))

    @kick.error
    @ban.error
    @purge.error
    async def mod_cooldown_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                embed=mod_embed("Devagar aí!", f"Aguarde {error.retry_after:.1f}s.", discord.Color.orange()),
                delete_after=5,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
