import json
import logging
import os
import discord
from discord.ext import commands

log = logging.getLogger("cog.playlist")

PLAYLISTS_FILE = os.path.join(os.path.dirname(__file__), "..", "playlists.json")


def _load() -> dict:
    if not os.path.exists(PLAYLISTS_FILE):
        return {}
    with open(PLAYLISTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def pl_embed(title: str, description: str = "", color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class Playlist(commands.Cog, name="Playlists"):
    """Gerenciamento de playlists salvas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="playlist", aliases=["pl"], invoke_without_command=True)
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
        data = _load()
        key = nome.lower()
        if key in data:
            return await ctx.send(embed=pl_embed("Erro", f"Já existe uma playlist chamada **{nome}**.", discord.Color.orange()))
        data[key] = {"nome": nome, "dono": ctx.author.id, "musicas": []}
        _save(data)
        await ctx.send(embed=pl_embed("Playlist criada", f"**{nome}** criada com sucesso.", discord.Color.green()))

    @playlist.command(name="add")
    async def add(self, ctx: commands.Context, nome: str, *, query: str):
        data = _load()
        key = nome.lower()
        if key not in data:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        data[key]["musicas"].append(query)
        _save(data)
        pos = len(data[key]["musicas"])
        await ctx.send(embed=pl_embed("Adicionado", f"`{pos}.` {query}\nadicionado em **{data[key]['nome']}**.", discord.Color.green()))

    @playlist.command(name="remove")
    async def remove(self, ctx: commands.Context, nome: str, index: int):
        data = _load()
        key = nome.lower()
        if key not in data:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        musicas = data[key]["musicas"]
        if not 1 <= index <= len(musicas):
            return await ctx.send(embed=pl_embed("Erro", "Número inválido.", discord.Color.orange()))
        removida = musicas.pop(index - 1)
        _save(data)
        await ctx.send(embed=pl_embed("Removido", f"**{removida}** removida de **{data[key]['nome']}**."))

    @playlist.command(name="ver")
    async def ver(self, ctx: commands.Context, *, nome: str):
        data = _load()
        key = nome.lower()
        if key not in data:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        pl = data[key]
        if not pl["musicas"]:
            return await ctx.send(embed=pl_embed(pl["nome"], "Playlist vazia."))
        itens = "\n".join(f"`{i}.` {m}" for i, m in enumerate(pl["musicas"], 1))
        embed = discord.Embed(title=pl["nome"], description=itens, color=discord.Color.blurple())
        embed.set_footer(text=f"{len(pl['musicas'])} música(s)")
        await ctx.send(embed=embed)

    @playlist.command(name="tocar")
    async def tocar(self, ctx: commands.Context, *, nome: str):
        data = _load()
        key = nome.lower()
        if key not in data:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        musicas = data[key]["musicas"]
        if not musicas:
            return await ctx.send(embed=pl_embed("Erro", "A playlist está vazia.", discord.Color.orange()))

        music_cog = self.bot.cogs.get("Música")
        if not music_cog:
            return await ctx.send(embed=pl_embed("Erro", "Cog de música não carregada.", discord.Color.red()))

        if not ctx.author.voice:
            return await ctx.send(embed=pl_embed("Erro", "Entre em um canal de voz primeiro.", discord.Color.red()))

        await ctx.send(embed=pl_embed("Carregando playlist", f"Adicionando **{len(musicas)}** música(s) de **{data[key]['nome']}**...", discord.Color.blurple()))

        for query in musicas:
            await ctx.invoke(music_cog.play, query=query)

    @playlist.command(name="deletar")
    async def deletar(self, ctx: commands.Context, *, nome: str):
        data = _load()
        key = nome.lower()
        if key not in data:
            return await ctx.send(embed=pl_embed("Erro", f"Playlist **{nome}** não encontrada.", discord.Color.red()))
        nome_real = data[key]["nome"]
        del data[key]
        _save(data)
        await ctx.send(embed=pl_embed("Deletada", f"Playlist **{nome_real}** removida.", discord.Color.red()))

    @playlist.command(name="lista")
    async def lista(self, ctx: commands.Context):
        data = _load()
        if not data:
            return await ctx.send(embed=pl_embed("Playlists", "Nenhuma playlist criada ainda."))
        itens = "\n".join(
            f"`{pl['nome']}` — {len(pl['musicas'])} música(s)"
            for pl in data.values()
        )
        await ctx.send(embed=pl_embed("Playlists disponíveis", itens))


async def setup(bot: commands.Bot):
    await bot.add_cog(Playlist(bot))
