import logging
import os
import aiosqlite
import discord
from discord.ext import commands

log = logging.getLogger("cog.playlist")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "playlists.db")


def pl_embed(title: str, description: str = "", color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Playlist(commands.Cog, name="Playlists"):
    """Gerenciamento de playlists salvas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._db: aiosqlite.Connection | None = None

    async def cog_load(self):
        # Conexão única persistente — evita abrir/fechar o arquivo a cada comando.
        self._db = await aiosqlite.connect(DB_PATH)
        # Necessário para o ON DELETE CASCADE funcionar (off por padrão no SQLite).
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                nome    TEXT NOT NULL,
                key     TEXT NOT NULL UNIQUE,
                dono_id INTEGER NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS musicas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                posicao     INTEGER NOT NULL,
                query       TEXT NOT NULL
            )
        """)
        await self._db.commit()
        log.info("Banco de playlists pronto em %s", DB_PATH)

    async def cog_unload(self):
        if self._db is not None:
            await self._db.close()
            self._db = None

    @commands.hybrid_group(name="playlist", aliases=["pl"], invoke_without_command=True)
    async def playlist(self, ctx: commands.Context):
        await ctx.send(
            embed=pl_embed(
                "Playlists",
                "Comandos disponíveis:\n"
                "`!playlist criar <nome>` — cria uma playlist\n"
                "`!playlist add <nome> <música/URL>` — adiciona uma música\n"
                "`!playlist remove <nome> <número>` — remove uma música\n"
                "`!playlist ver <nome>` — lista as músicas\n"
                "`!playlist tocar <nome>` — coloca todas na fila\n"
                "`!playlist deletar <nome>` — apaga a playlist\n"
                "`!playlist lista` — mostra todas as playlists",
            )
        )

    @playlist.command(name="criar")
    async def criar(self, ctx: commands.Context, *, nome: str):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id FROM playlists WHERE key = ?", (key,)) as cur:
            if await cur.fetchone():
                return await ctx.send(embed=pl_embed("Erro", f"Já existe uma playlist chamada **{nome}**.", discord.Color.orange()))
        await self._db.execute(
            "INSERT INTO playlists (nome, key, dono_id) VALUES (?, ?, ?)",
            (nome.strip(), key, ctx.author.id),
        )
        await self._db.commit()
        await ctx.send(embed=pl_embed("Playlist criada", f"**{nome}** criada com sucesso.", discord.Color.green()))

    @playlist.command(name="add")
    async def add(self, ctx: commands.Context, nome: str, *, query: str):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id FROM playlists WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl_id = row[0]
        async with self._db.execute("SELECT COALESCE(MAX(posicao), 0) FROM musicas WHERE playlist_id = ?", (pl_id,)) as cur:
            max_pos = (await cur.fetchone())[0]
        await self._db.execute(
            "INSERT INTO musicas (playlist_id, posicao, query) VALUES (?, ?, ?)",
            (pl_id, max_pos + 1, query.strip()),
        )
        await self._db.commit()
        await ctx.send(embed=pl_embed("Adicionado", f"`{max_pos + 1}.` {query}\nadicionado em **{nome}**.", discord.Color.green()))

    @playlist.command(name="remove")
    async def remove(self, ctx: commands.Context, nome: str, index: int):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id FROM playlists WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl_id = row[0]
        async with self._db.execute(
            "SELECT id, query FROM musicas WHERE playlist_id = ? ORDER BY posicao", (pl_id,)
        ) as cur:
            musicas = await cur.fetchall()
        if not 1 <= index <= len(musicas):
            return await ctx.send(embed=pl_embed("Erro", "Número inválido.", discord.Color.orange()))
        rid, query = musicas[index - 1]
        await self._db.execute("DELETE FROM musicas WHERE id = ?", (rid,))
        # Reordena posições
        for new_pos, (mid, _) in enumerate(musicas, 1):
            if mid != rid:
                await self._db.execute("UPDATE musicas SET posicao = ? WHERE id = ?", (new_pos if new_pos < index else new_pos - 1, mid))
        await self._db.commit()
        await ctx.send(embed=pl_embed("Removido", f"**{query}** removida de **{nome}**."))

    @playlist.command(name="ver")
    async def ver(self, ctx: commands.Context, *, nome: str):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id, nome FROM playlists WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl_id, nome_real = row
        async with self._db.execute(
            "SELECT query FROM musicas WHERE playlist_id = ? ORDER BY posicao", (pl_id,)
        ) as cur:
            musicas = [r[0] for r in await cur.fetchall()]

        if not musicas:
            return await ctx.send(embed=pl_embed(nome_real, "Playlist vazia."))
        itens = "\n".join(f"`{i}.` {m}" for i, m in enumerate(musicas, 1))
        embed = discord.Embed(title=nome_real, description=itens[:4000], color=discord.Color.blurple())
        embed.set_footer(text=f"{len(musicas)} música(s)")
        await ctx.send(embed=embed)

    @playlist.command(name="tocar")
    async def tocar(self, ctx: commands.Context, *, nome: str):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id, nome FROM playlists WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl_id, nome_real = row
        async with self._db.execute(
            "SELECT query FROM musicas WHERE playlist_id = ? ORDER BY posicao", (pl_id,)
        ) as cur:
            musicas = [r[0] for r in await cur.fetchall()]

        if not musicas:
            return await ctx.send(embed=pl_embed("Erro", "A playlist está vazia.", discord.Color.orange()))

        music_cog = self.bot.cogs.get("Música")
        if not music_cog:
            return await ctx.send(embed=pl_embed("Erro", "Cog de música não carregada.", discord.Color.red()))
        if not ctx.author.voice:
            return await ctx.send(embed=pl_embed("Erro", "Entre em um canal de voz primeiro.", discord.Color.red()))

        # Enfileira tudo de uma vez como faixas "lazy" — a 1ª resolve na hora
        # e o resto é pré-carregado em background. Sem cooldown, sem espera.
        songs = [{
            "title": q,
            "url": "",
            "duration": 0,
            "thumbnail": "",
            "uploader": "Playlist",
            "source": "",
            "_needs_fetch": True,
            "_query": q,
        } for q in musicas]
        await music_cog._enqueue_many(ctx, songs, f"playlist **{nome_real}**")

    @playlist.command(name="deletar")
    async def deletar(self, ctx: commands.Context, *, nome: str):
        key = nome.lower().strip()
        async with self._db.execute("SELECT id, nome FROM playlists WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl_id, nome_real = row
        await self._db.execute("DELETE FROM musicas WHERE playlist_id = ?", (pl_id,))
        await self._db.execute("DELETE FROM playlists WHERE id = ?", (pl_id,))
        await self._db.commit()
        await ctx.send(embed=pl_embed("Deletada", f"Playlist **{nome_real}** removida.", discord.Color.red()))

    @playlist.command(name="lista")
    async def lista(self, ctx: commands.Context):
        async with self._db.execute("""
            SELECT p.nome, COUNT(m.id)
            FROM playlists p
            LEFT JOIN musicas m ON m.playlist_id = p.id
            GROUP BY p.id
            ORDER BY p.nome
        """) as cur:
            rows = await cur.fetchall()

        if not rows:
            return await ctx.send(embed=pl_embed("Playlists", "Nenhuma playlist criada ainda."))
        itens = "\n".join(f"`{nome}` — {qtd} música(s)" for nome, qtd in rows)
        await ctx.send(embed=pl_embed("Playlists disponíveis", itens))


async def setup(bot: commands.Bot):
    await bot.add_cog(Playlist(bot))
