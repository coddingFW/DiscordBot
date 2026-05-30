"""Auto-moderação: filtro de spam, palavras proibidas e links."""
import asyncio
import logging
import os
import re
import time
from collections import defaultdict

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from .logs import send_log, log_embed

log = logging.getLogger("cog.automod")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "automod.db")

_URL_RE = re.compile(
    r"https?://\S+|discord\.gg/\S+|www\.\S+\.\w{2,}",
    re.IGNORECASE,
)

DEFAULT_SPAM_LIMIT = 5   # mensagens
DEFAULT_SPAM_WINDOW = 5  # segundos


def _embed(title: str, desc: str = "", color=discord.Color.orange()) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)


class AutoMod(commands.Cog, name="AutoMod"):
    """Moderação automática: anti-spam, palavras proibidas e filtro de links."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._db: aiosqlite.Connection | None = None
        self._config: dict[int, dict] = {}       # guild_id → config dict
        self._words: dict[int, set[str]] = {}    # guild_id → set de palavras
        self._tracker: defaultdict = defaultdict(list)  # (guild, channel, user) → timestamps

    async def cog_load(self):
        self._db = await aiosqlite.connect(DB_PATH)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS automod_config (
                guild_id      INTEGER PRIMARY KEY,
                spam_enabled  INTEGER NOT NULL DEFAULT 0,
                spam_limit    INTEGER NOT NULL DEFAULT 5,
                spam_window   INTEGER NOT NULL DEFAULT 5,
                links_enabled INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS automod_words (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                word     TEXT NOT NULL,
                UNIQUE(guild_id, word)
            )
        """)
        await self._db.commit()

        async with self._db.execute("SELECT guild_id, spam_enabled, spam_limit, spam_window, links_enabled FROM automod_config") as cur:
            async for gid, sp_en, sp_lim, sp_win, lk_en in cur:
                self._config[gid] = {
                    "spam_enabled": bool(sp_en),
                    "spam_limit": sp_lim,
                    "spam_window": sp_win,
                    "links_enabled": bool(lk_en),
                }
        async with self._db.execute("SELECT guild_id, word FROM automod_words") as cur:
            async for gid, word in cur:
                self._words.setdefault(gid, set()).add(word.lower())

        log.info("AutoMod carregado (%d servidores)", len(self._config))

    async def cog_unload(self):
        if self._db:
            await self._db.close()

    def _cfg(self, guild_id: int) -> dict:
        return self._config.get(guild_id, {
            "spam_enabled": False, "spam_limit": DEFAULT_SPAM_LIMIT,
            "spam_window": DEFAULT_SPAM_WINDOW, "links_enabled": False,
        })

    async def _save_config(self, guild_id: int):
        c = self._cfg(guild_id)
        await self._db.execute("""
            INSERT INTO automod_config (guild_id, spam_enabled, spam_limit, spam_window, links_enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                spam_enabled=excluded.spam_enabled,
                spam_limit=excluded.spam_limit,
                spam_window=excluded.spam_window,
                links_enabled=excluded.links_enabled
        """, (guild_id, int(c["spam_enabled"]), c["spam_limit"], c["spam_window"], int(c["links_enabled"])))
        await self._db.commit()

    # ── Listener ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return  # moderadores são imunes

        gid = message.guild.id
        cfg = self._cfg(gid)
        words = self._words.get(gid, set())

        # Filtro de palavras
        if words:
            lower = message.content.lower()
            for word in words:
                if word in lower:
                    await self._punir(message, f"Palavra proibida detectada.")
                    return

        # Filtro de links
        if cfg["links_enabled"] and _URL_RE.search(message.content):
            await self._punir(message, "Links não são permitidos neste servidor.")
            return

        # Anti-spam
        if cfg["spam_enabled"]:
            key = (gid, message.channel.id, message.author.id)
            now = time.monotonic()
            window = cfg["spam_window"]
            self._tracker[key] = [t for t in self._tracker[key] if now - t < window]
            self._tracker[key].append(now)
            if len(self._tracker[key]) > cfg["spam_limit"]:
                await self._punir(message, f"Spam detectado ({cfg['spam_limit']}+ msgs em {window}s).")
                self._tracker[key] = []

    async def _punir(self, message: discord.Message, motivo: str):
        try:
            await message.delete()
        except discord.Forbidden:
            pass

        aviso = await message.channel.send(
            embed=_embed("🤖 AutoMod", f"{message.author.mention} — {motivo}", discord.Color.red())
        )
        await asyncio.sleep(5)
        try:
            await aviso.delete()
        except discord.NotFound:
            pass

        await send_log(message.guild, log_embed(
            "🤖 AutoMod — Violação", discord.Color.red(),
            Usuário=f"{message.author} ({message.author.id})",
            Canal=f"#{message.channel.name}",
            Motivo=motivo,
        ))

    # ── Comandos ──────────────────────────────────────────────────────────────

    @commands.hybrid_group(name="automod", aliases=["am"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def automod(self, ctx: commands.Context):
        """Mostra o status atual do AutoMod neste servidor."""
        cfg = self._cfg(ctx.guild.id)
        words = self._words.get(ctx.guild.id, set())
        embed = discord.Embed(title="🤖 AutoMod — Status", color=discord.Color.blurple())
        embed.add_field(
            name="Anti-Spam",
            value=f"{'✅ Ativo' if cfg['spam_enabled'] else '❌ Inativo'}\n"
                  f"Limite: **{cfg['spam_limit']}** msgs / **{cfg['spam_window']}s**",
        )
        embed.add_field(
            name="Filtro de Links",
            value="✅ Ativo" if cfg["links_enabled"] else "❌ Inativo",
        )
        embed.add_field(
            name=f"Palavras proibidas ({len(words)})",
            value=", ".join(f"`{w}`" for w in sorted(words)[:15]) or "Nenhuma",
            inline=False,
        )
        embed.set_footer(text="!automod spam | links | palavras add/remove")
        await ctx.send(embed=embed)

    @automod.command(name="spam")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(acao="on ou off", limite="Máximo de msgs (padrão 5)", janela="Janela em segundos (padrão 5)")
    async def automod_spam(self, ctx: commands.Context, acao: str, limite: int = None, janela: int = None):
        """Ativa/desativa o filtro de spam. Ex: !automod spam on 6 8"""
        acao = acao.lower()
        if acao not in ("on", "off"):
            return await ctx.send(embed=_embed("Erro", "Use `on` ou `off`.", discord.Color.red()))
        cfg = self._config.setdefault(ctx.guild.id, {
            "spam_enabled": False, "spam_limit": DEFAULT_SPAM_LIMIT,
            "spam_window": DEFAULT_SPAM_WINDOW, "links_enabled": False,
        })
        cfg["spam_enabled"] = (acao == "on")
        if limite: cfg["spam_limit"] = max(2, limite)
        if janela: cfg["spam_window"] = max(2, janela)
        await self._save_config(ctx.guild.id)
        await ctx.send(embed=_embed(
            "Anti-Spam atualizado",
            f"{'✅ Ativado' if cfg['spam_enabled'] else '❌ Desativado'}\n"
            f"Limite: **{cfg['spam_limit']}** msgs em **{cfg['spam_window']}s**",
            discord.Color.green() if cfg["spam_enabled"] else discord.Color.red(),
        ))

    @automod.command(name="links")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(acao="on ou off")
    async def automod_links(self, ctx: commands.Context, acao: str):
        """Ativa/desativa o filtro de links."""
        acao = acao.lower()
        if acao not in ("on", "off"):
            return await ctx.send(embed=_embed("Erro", "Use `on` ou `off`.", discord.Color.red()))
        cfg = self._config.setdefault(ctx.guild.id, {
            "spam_enabled": False, "spam_limit": DEFAULT_SPAM_LIMIT,
            "spam_window": DEFAULT_SPAM_WINDOW, "links_enabled": False,
        })
        cfg["links_enabled"] = (acao == "on")
        await self._save_config(ctx.guild.id)
        await ctx.send(embed=_embed(
            "Filtro de Links atualizado",
            "✅ Ativado" if cfg["links_enabled"] else "❌ Desativado",
            discord.Color.green() if cfg["links_enabled"] else discord.Color.red(),
        ))

    @automod.group(name="palavras", aliases=["words"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def automod_palavras(self, ctx: commands.Context):
        """Lista as palavras proibidas do servidor."""
        words = self._words.get(ctx.guild.id, set())
        if not words:
            return await ctx.send(embed=_embed("Palavras proibidas", "Nenhuma cadastrada."))
        await ctx.send(embed=_embed(
            f"Palavras proibidas ({len(words)})",
            ", ".join(f"`{w}`" for w in sorted(words)),
        ))

    @automod_palavras.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def palavras_add(self, ctx: commands.Context, *, palavra: str):
        """Adiciona uma palavra à lista de proibidas."""
        word = palavra.lower().strip()
        await self._db.execute(
            "INSERT OR IGNORE INTO automod_words (guild_id, word) VALUES (?, ?)",
            (ctx.guild.id, word),
        )
        await self._db.commit()
        self._words.setdefault(ctx.guild.id, set()).add(word)
        await ctx.send(embed=_embed("Palavra adicionada", f"`{word}` adicionada à lista.", discord.Color.green()))

    @automod_palavras.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def palavras_remove(self, ctx: commands.Context, *, palavra: str):
        """Remove uma palavra da lista de proibidas."""
        word = palavra.lower().strip()
        await self._db.execute(
            "DELETE FROM automod_words WHERE guild_id = ? AND word = ?",
            (ctx.guild.id, word),
        )
        await self._db.commit()
        self._words.get(ctx.guild.id, set()).discard(word)
        await ctx.send(embed=_embed("Palavra removida", f"`{word}` removida.", discord.Color.green()))


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
