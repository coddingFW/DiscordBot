import logging
import os
import time
from datetime import datetime, timezone

import aiosqlite
import discord
from discord.ext import commands

from .logs import send_log, log_embed

log = logging.getLogger("cog.warns")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "warns.db")

# Warn count → ação automática ("mute" ou "ban")
WARN_THRESHOLDS: dict[int, str] = {3: "mute", 5: "ban"}


def _embed(title: str, description: str = "", color=discord.Color.orange()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Warns(commands.Cog, name="Avisos"):
    """Histórico persistente de avisos com ações automáticas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._db: aiosqlite.Connection | None = None

    async def cog_load(self):
        self._db = await aiosqlite.connect(DB_PATH)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id  INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,
                mod_id    INTEGER NOT NULL,
                reason    TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )
        """)
        await self._db.commit()
        log.info("Banco de warns pronto em %s", DB_PATH)

    async def cog_unload(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def _apply_auto_action(self, ctx: commands.Context, member: discord.Member, total: int):
        action = WARN_THRESHOLDS.get(total)
        if action == "mute":
            muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if not muted_role:
                muted_role = await ctx.guild.create_role(name="Muted")
                for channel in ctx.guild.channels:
                    await channel.set_permissions(muted_role, send_messages=False, speak=False)
            if muted_role not in member.roles:
                await member.add_roles(muted_role, reason=f"Auto-mute: {total} avisos")
            await ctx.send(embed=_embed(
                "Auto-mute aplicado",
                f"{member.mention} foi silenciado automaticamente por atingir **{total} avisos**.",
                discord.Color.red(),
            ))
            await send_log(ctx.guild, log_embed(
                "🔇 Auto-mute (avisos)", discord.Color.red(),
                Usuário=f"{member} ({member.id})",
                Avisos=str(total),
            ))
        elif action == "ban":
            await member.ban(reason=f"Auto-ban: {total} avisos")
            await ctx.send(embed=_embed(
                "Auto-ban aplicado",
                f"{member.mention} foi banido automaticamente por atingir **{total} avisos**.",
                discord.Color.dark_red(),
            ))
            await send_log(ctx.guild, log_embed(
                "🔨 Auto-ban (avisos)", discord.Color.dark_red(),
                Usuário=f"{member} ({member.id})",
                Avisos=str(total),
            ))

    @commands.command(name="warn", help="Registra um aviso para um membro (histórico persistente).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        ts = int(time.time())
        await self._db.execute(
            "INSERT INTO warns (guild_id, user_id, mod_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, member.id, ctx.author.id, reason, ts),
        )
        await self._db.commit()

        async with self._db.execute(
            "SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id),
        ) as cur:
            (total,) = await cur.fetchone()

        try:
            await member.send(embed=discord.Embed(
                title=f"Aviso em {ctx.guild.name}",
                description=f"Você recebeu um aviso ({total}º).\n**Motivo:** {reason}",
                color=discord.Color.orange(),
            ))
            dm_note = ""
        except discord.Forbidden:
            dm_note = "\n*(DM bloqueada — membro não foi notificado)*"

        next_action = WARN_THRESHOLDS.get(total + 1)
        proximo = f"\n⚠️ Próximo aviso: **{next_action}** automático." if next_action else ""

        await ctx.send(embed=_embed(
            f"Aviso #{total} registrado",
            f"{member.mention} recebeu um aviso.\n**Motivo:** {reason}{dm_note}{proximo}",
        ))
        await send_log(ctx.guild, log_embed(
            f"⚠️ Aviso #{total}", discord.Color.orange(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
            Motivo=reason,
        ))
        log.info("%s avisou %s (aviso #%d). Motivo: %s", ctx.author, member, total, reason)

        await self._apply_auto_action(ctx, member, total)

    @commands.command(name="warns", aliases=["infrações", "historico"], help="Mostra o histórico de avisos de um membro.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def list_warns(self, ctx: commands.Context, member: discord.Member):
        async with self._db.execute(
            "SELECT id, mod_id, reason, timestamp FROM warns "
            "WHERE guild_id = ? AND user_id = ? ORDER BY timestamp",
            (ctx.guild.id, member.id),
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return await ctx.send(embed=_embed(
                f"Avisos de {member.display_name}",
                "Nenhum aviso registrado.",
                discord.Color.green(),
            ))

        lines = []
        for wid, mod_id, reason, ts in rows:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")
            lines.append(f"`#{wid}` {dt} — **{reason}** *(por <@{mod_id}>)*")

        embed = discord.Embed(
            title=f"Avisos de {member.display_name}",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Total: {len(rows)} aviso(s)")
        await ctx.send(embed=embed)

    @commands.command(name="delwarn", aliases=["removerwarn"], help="Remove um aviso específico pelo ID.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def del_warn(self, ctx: commands.Context, warn_id: int):
        async with self._db.execute(
            "SELECT user_id FROM warns WHERE id = ? AND guild_id = ?",
            (warn_id, ctx.guild.id),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            return await ctx.send(embed=_embed("Erro", f"Aviso `#{warn_id}` não encontrado.", discord.Color.red()))

        user_id = row[0]
        await self._db.execute("DELETE FROM warns WHERE id = ?", (warn_id,))
        await self._db.commit()
        await ctx.send(embed=_embed(
            "Aviso removido",
            f"Aviso `#{warn_id}` de <@{user_id}> foi removido.",
            discord.Color.green(),
        ))
        log.info("%s removeu o aviso #%d de user_id=%d", ctx.author, warn_id, user_id)

    @commands.command(name="clearwarns", aliases=["limpar-avisos"], help="Remove todos os avisos de um membro (admin).")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def clear_warns(self, ctx: commands.Context, member: discord.Member):
        await self._db.execute(
            "DELETE FROM warns WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id),
        )
        await self._db.commit()
        await ctx.send(embed=_embed(
            "Avisos limpos",
            f"Todos os avisos de {member.mention} foram removidos.",
            discord.Color.green(),
        ))
        await send_log(ctx.guild, log_embed(
            "🧹 Avisos Removidos", discord.Color.green(),
            Usuário=f"{member} ({member.id})",
            Moderador=str(ctx.author),
        ))
        log.info("%s limpou avisos de %s", ctx.author, member)


async def setup(bot: commands.Bot):
    await bot.add_cog(Warns(bot))
