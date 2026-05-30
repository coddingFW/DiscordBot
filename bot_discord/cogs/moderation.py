"""Moderação: kick, ban, unban, purge, mute (timeout nativo) e unmute."""
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .logs import send_log, log_embed

log = logging.getLogger("cog.moderation")

# ── Helpers de duração ────────────────────────────────────────────────────────
_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d)$", re.IGNORECASE)
_MAX_TIMEOUT = timedelta(days=28)  # limite do Discord


def _parse_duration(s: str) -> timedelta | None:
    """Converte '10m', '2h', '1d', '30s' → timedelta. Retorna None se inválido."""
    m = _DURATION_RE.match(s.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return timedelta(seconds=n * mult[unit])


def _fmt_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total >= 86400:
        return f"{total // 86400}d"
    if total >= 3600:
        return f"{total // 3600}h"
    if total >= 60:
        return f"{total // 60}m"
    return f"{total}s"


def mod_embed(title: str, description: str, color=discord.Color.red()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Moderation(commands.Cog, name="Moderação"):
    """Comandos de moderação do servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── kick ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="kick", help="Expulsa um membro do servidor.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.guild_only()
    @app_commands.describe(member="Membro a expulsar", reason="Motivo")
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sem motivo"):
        await member.kick(reason=reason)
        await ctx.send(embed=mod_embed(
            "Membro Expulso",
            f"{member.mention} foi expulso.\n**Motivo:** {reason}",
            discord.Color.orange(),
        ))
        await send_log(ctx.guild, log_embed(
            "👢 Membro Expulso", discord.Color.orange(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s expulsou %s. Motivo: %s", ctx.author, member, reason)

    # ── ban ──────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="ban", help="Bane um membro do servidor.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.guild_only()
    @app_commands.describe(member="Membro a banir", reason="Motivo")
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sem motivo"):
        await member.ban(reason=reason)
        await ctx.send(embed=mod_embed(
            "Membro Banido",
            f"{member.mention} foi banido.\n**Motivo:** {reason}",
        ))
        await send_log(ctx.guild, log_embed(
            "🔨 Membro Banido", discord.Color.red(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s baniu %s. Motivo: %s", ctx.author, member, reason)

    # ── unban ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="unban", help="Remove o ban de um usuário (ID ou Nome#0000).")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    @app_commands.describe(identifier="ID numérico ou Nome#0000 do usuário banido")
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
            "✅ Ban Removido", discord.Color.green(),
            Usuário=f"{user} ({user.id})",
            Moderador=str(ctx.author),
        ))

    # ── purge ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="purge", help="Apaga mensagens do canal (máx. 100).")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @commands.cooldown(1, 10, commands.BucketType.channel)
    @commands.guild_only()
    @app_commands.describe(amount="Quantidade de mensagens a apagar (1–100)")
    async def purge(self, ctx: commands.Context, amount: int):
        if not 1 <= amount <= 100:
            return await ctx.send(embed=mod_embed("Erro", "Informe um número entre 1 e 100.", discord.Color.orange()))
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(
            embed=mod_embed("Mensagens Apagadas", f"{len(deleted) - 1} mensagens removidas.", discord.Color.orange())
        )
        await msg.delete(delay=5)

    # ── mute (timeout nativo do Discord) ─────────────────────────────────────

    @commands.hybrid_command(name="mute", help="Silencia um membro com timeout do Discord. Ex: !mute @user 10m spam")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    @app_commands.describe(
        member="Membro a silenciar",
        duracao="Duração: 30s, 10m, 2h, 1d (padrão: 28d)",
        motivo="Motivo do silence",
    )
    async def mute(self, ctx: commands.Context, member: discord.Member, duracao: str = "28d", *, motivo: str = "Sem motivo"):
        delta = _parse_duration(duracao)
        if delta is None:
            # duracao não é válida — trata como início do motivo
            motivo = f"{duracao} {motivo}".strip()
            delta = timedelta(days=28)

        delta = min(delta, _MAX_TIMEOUT)
        until = datetime.now(timezone.utc) + delta
        dur_label = _fmt_duration(delta)

        try:
            await member.timeout(until, reason=motivo)
        except discord.Forbidden:
            return await ctx.send(embed=mod_embed("Erro", "Não tenho permissão para silenciar este membro.", discord.Color.orange()))

        await ctx.send(embed=mod_embed(
            "Membro Silenciado",
            f"{member.mention} foi silenciado por **{dur_label}**.\n**Motivo:** {motivo}",
            discord.Color.dark_gray(),
        ))
        await send_log(ctx.guild, log_embed(
            "🔇 Membro Silenciado (timeout)", discord.Color.dark_gray(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Duração=dur_label,
            Motivo=motivo,
        ))
        log.info("%s silenciou %s por %s. Motivo: %s", ctx.author, member, dur_label, motivo)

    # ── unmute ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="unmute", help="Remove o timeout de um membro.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    @app_commands.describe(member="Membro para remover o silêncio")
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        if not member.is_timed_out():
            return await ctx.send(embed=mod_embed("Aviso", f"{member.mention} não está silenciado.", discord.Color.orange()))
        await member.timeout(None, reason=f"Timeout removido por {ctx.author}")
        await ctx.send(embed=mod_embed("Voz Restaurada", f"{member.mention} pode falar novamente.", discord.Color.green()))
        await send_log(ctx.guild, log_embed(
            "🔊 Timeout Removido", discord.Color.green(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
        ))

    # ── error handlers ────────────────────────────────────────────────────────

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
