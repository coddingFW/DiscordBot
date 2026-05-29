"""Testes das operações de playlist no SQLite, com banco temporário e ctx mockado."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.playlist as pl_mod
from cogs.playlist import Playlist


def make_ctx():
    """ctx mínimo: author com id e um send() assíncrono espionável."""
    return SimpleNamespace(author=SimpleNamespace(id=123), send=AsyncMock())


@pytest.fixture
async def cog(tmp_path, monkeypatch):
    # Aponta o DB para um arquivo temporário isolado por teste.
    monkeypatch.setattr(pl_mod, "DB_PATH", str(tmp_path / "test.db"))
    c = Playlist(bot=None)
    await c.cog_load()
    yield c
    await c.cog_unload()


def _ultimo_embed(ctx):
    """Retorna o embed do último ctx.send()."""
    return ctx.send.call_args.kwargs["embed"]


async def test_criar_playlist(cog):
    ctx = make_ctx()
    await Playlist.criar.callback(cog, ctx, nome="Rock")
    assert "criada" in _ultimo_embed(ctx).title.lower()


async def test_criar_duplicada(cog):
    ctx = make_ctx()
    await Playlist.criar.callback(cog, ctx, nome="Rock")
    await Playlist.criar.callback(cog, ctx, nome="rock")  # mesma key (lower)
    assert _ultimo_embed(ctx).title == "Erro"


async def test_add_em_playlist_inexistente(cog):
    ctx = make_ctx()
    await Playlist.add.callback(cog, ctx, "Fantasma", query="alguma música")
    assert _ultimo_embed(ctx).title == "Erro"


async def test_add_e_ver(cog):
    ctx = make_ctx()
    await Playlist.criar.callback(cog, ctx, nome="Pop")
    await Playlist.add.callback(cog, ctx, "Pop", query="musica um")
    await Playlist.add.callback(cog, ctx, "Pop", query="musica dois")
    await Playlist.ver.callback(cog, ctx, nome="Pop")
    embed = _ultimo_embed(ctx)
    assert "musica um" in embed.description
    assert "musica dois" in embed.description


async def test_remove_reordena(cog):
    ctx = make_ctx()
    await Playlist.criar.callback(cog, ctx, nome="Mix")
    for q in ["a", "b", "c"]:
        await Playlist.add.callback(cog, ctx, "Mix", query=q)
    await Playlist.remove.callback(cog, ctx, "Mix", 2)  # remove "b"
    await Playlist.ver.callback(cog, ctx, nome="Mix")
    desc = _ultimo_embed(ctx).description
    assert "a" in desc and "c" in desc
    assert "`1.` a" in desc and "`2.` c" in desc  # reordenado


async def test_deletar_cascateia_musicas(cog):
    ctx = make_ctx()
    await Playlist.criar.callback(cog, ctx, nome="Temp")
    await Playlist.add.callback(cog, ctx, "Temp", query="x")
    await Playlist.deletar.callback(cog, ctx, nome="Temp")
    # Não devem sobrar músicas órfãs no banco.
    async with cog._db.execute("SELECT COUNT(*) FROM musicas") as cur:
        total = (await cur.fetchone())[0]
    assert total == 0


async def test_lista_vazia(cog):
    ctx = make_ctx()
    await Playlist.lista.callback(cog, ctx)
    assert "Nenhuma playlist" in _ultimo_embed(ctx).description
