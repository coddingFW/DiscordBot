import logging
import os
import time
from datetime import datetime, timezone, timedelta

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from .logs import send_log, log_embed

log = logging.getLogger("cog.warns")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "warns.db")

WARN_THRESHOLDS: dict[int, str] = {3: "mute", 5: "ban"}


def _embed(title: str, description: str = "", color=discord.Color.orange()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Warns(commands.Cog, name="Avisos"):
    """Historico persistente de avisos com acoes automaticas."""

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
            # Usa timeout nativo do Discord (28d)
            try:
                until = datetime.now(timezone.utc) + timedelta(days=28)
                await member.timeout(until, reason=f"Auto-mute: {total} avisos")
            except discord.Forbidden:
                pass
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

    @commands.hybrid_command(name="warn", help="Registra um aviso para um membro (historico persistente).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    @app_commands.describe(member="Membro a avisar", reason="Motivo do aviso")
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
                description=f"Voce recebeu um aviso ({total}o).\n**Motivo:** {reason}",
                color=discord.Color.orange(),
            ))
            dm_note = ""
        except discord.Forbidden:
            dm_note = "\n*(DM bloqueada — membro nao foi notificado)*"

        next_action = WARN_THRESHOLDS.get(total + 1)
        proximo = f"\n⚠️ Proximo aviso: **{next_action}** automatico." if next_action else ""

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

    @commands.hybrid_command(name="warns", aliases=["historico"], help="Mostra o historico de avisos de um membro.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    @app_commands.describe(member="Membro para ver o historico")
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

    @commands.hybrid_command(name="delwarn", aliases=["removerwarn"], help="Remove um aviso especifico pelo ID.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    @app_commands.describe(warn_id="ID do aviso a remover")
    async def del_warn(self, ctx: commands.Context, warn_id: int):
        async with self._db.execute(
            "SELECT user_id FROM warns WHERE id = ? AND guild_id = ?",
            (warn_id, ctx.guild.id),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            return await ctx.send(embed=_embed("Erro", f"Aviso `#{warn_id}` nao encontrado.", discord.Color.red()))

        user_id = row[0]
        await self._db.execute("DELETE FROM warns WHERE id = ?", (warn_id,))
        await self._db.commit()
        await ctx.send(embed=_embed(
            "Aviso removido",
            f"Aviso `#{warn_id}` de <@{user_id}> foi removido.",
            discord.Color.green(),
        ))
        log.info("%s removeu o aviso #%d de user_id=%d", ctx.author, warn_id, user_id)

    @commands.hybrid_command(name="clearwarns", aliases=["limpar-avisos"], help="Remove todos os avisos de um membro (admin).")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @app_commands.describe(member="Membro para limpar os avisos")
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
