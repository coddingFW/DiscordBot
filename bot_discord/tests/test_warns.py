"""Testes do sistema de avisos persistentes — banco temporário, sem Discord real."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.warns as warns_mod
from cogs.warns import Warns


def make_member(id=1, name="usuario", roles=None, display_name=None):
    m = MagicMock()
    m.id = id
    m.name = name
    m.display_name = display_name or name
    m.roles = roles or []
    m.send = AsyncMock()
    m.add_roles = AsyncMock()
    m.ban = AsyncMock()
    return m


def make_guild(guild_id=1, members=None):
    guild = SimpleNamespace()
    guild.id = guild_id
    guild.name = "Servidor Teste"
    guild.roles = []
    guild.channels = []
    guild.members = members or []
    guild.create_role = AsyncMock(return_value=SimpleNamespace(name="Muted"))
    return guild


def make_ctx(author_id=999, guild=None):
    ctx = SimpleNamespace()
    ctx.author = SimpleNamespace(id=author_id, __str__=lambda s: "Mod#0001")
    ctx.guild = guild or make_guild()
    ctx.send = AsyncMock()
    return ctx


@pytest.fixture
async def cog(tmp_path, monkeypatch):
    monkeypatch.setattr(warns_mod, "DB_PATH", str(tmp_path / "warns.db"))
    c = Warns(bot=None)
    await c.cog_load()
    yield c
    await c.cog_unload()


def _embed(ctx):
    return ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]


# ── warn básico ───────────────────────────────────────────────────────────────

async def test_warn_registra_no_banco(cog):
    member = make_member(id=10)
    ctx = make_ctx()
    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="spam")

    async with cog._db.execute("SELECT COUNT(*) FROM warns WHERE user_id = 10") as cur:
        (total,) = await cur.fetchone()
    assert total == 1


async def test_warn_incrementa_contador(cog):
    member = make_member(id=20)
    ctx = make_ctx()
    with patch("cogs.warns.send_log", new=AsyncMock()):
        for _ in range(3):
            await Warns.warn.callback(cog, ctx, member, reason="flood")

    async with cog._db.execute("SELECT COUNT(*) FROM warns WHERE user_id = 20") as cur:
        (total,) = await cur.fetchone()
    assert total == 3


async def test_warn_titulo_exibe_numero_correto(cog):
    member = make_member(id=30)
    ctx = make_ctx()
    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="xingamento")

    embed = _embed(ctx)
    assert "1" in embed.title


async def test_warn_envia_dm_ao_membro(cog):
    member = make_member(id=40)
    ctx = make_ctx()
    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="ofensa")

    member.send.assert_called_once()


# ── ações automáticas ─────────────────────────────────────────────────────────

async def test_auto_mute_no_terceiro_aviso(cog):
    guild = make_guild()
    member = make_member(id=50)
    ctx = make_ctx(guild=guild)

    with patch("cogs.warns.send_log", new=AsyncMock()):
        for i in range(3):
            await Warns.warn.callback(cog, ctx, member, reason=f"warn {i+1}")

    member.add_roles.assert_called_once()


async def test_auto_ban_no_quinto_aviso(cog):
    guild = make_guild()
    member = make_member(id=60)
    ctx = make_ctx(guild=guild)

    with patch("cogs.warns.send_log", new=AsyncMock()):
        for i in range(5):
            await Warns.warn.callback(cog, ctx, member, reason=f"warn {i+1}")

    member.ban.assert_called_once()


async def test_sem_acao_automatica_antes_do_limiar(cog):
    guild = make_guild()
    member = make_member(id=70)
    ctx = make_ctx(guild=guild)

    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="primeiro")
        await Warns.warn.callback(cog, ctx, member, reason="segundo")

    member.add_roles.assert_not_called()
    member.ban.assert_not_called()


# ── list_warns ────────────────────────────────────────────────────────────────

async def test_list_warns_sem_historico(cog):
    member = make_member(id=80)
    ctx = make_ctx()
    await Warns.list_warns.callback(cog, ctx, member)

    embed = _embed(ctx)
    assert "Nenhum aviso" in embed.description


async def test_list_warns_exibe_historico(cog):
    member = make_member(id=90)
    ctx = make_ctx()

    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="motivo A")
        await Warns.warn.callback(cog, ctx, member, reason="motivo B")

    await Warns.list_warns.callback(cog, ctx, member)
    embed = _embed(ctx)
    assert "motivo A" in embed.description
    assert "motivo B" in embed.description
    assert embed.footer.text == "Total: 2 aviso(s)"


# ── del_warn ──────────────────────────────────────────────────────────────────

async def test_delwarn_remove_aviso(cog):
    member = make_member(id=100)
    ctx = make_ctx()

    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.warn.callback(cog, ctx, member, reason="teste")

    async with cog._db.execute("SELECT id FROM warns WHERE user_id = 100") as cur:
        warn_id = (await cur.fetchone())[0]

    await Warns.del_warn.callback(cog, ctx, warn_id)

    async with cog._db.execute("SELECT COUNT(*) FROM warns WHERE user_id = 100") as cur:
        (total,) = await cur.fetchone()
    assert total == 0


async def test_delwarn_id_inexistente(cog):
    ctx = make_ctx()
    await Warns.del_warn.callback(cog, ctx, 9999)
    embed = _embed(ctx)
    assert embed.title == "Erro"


# ── clear_warns ───────────────────────────────────────────────────────────────

async def test_clearwarns_remove_todos(cog):
    member = make_member(id=110)
    ctx = make_ctx()

    with patch("cogs.warns.send_log", new=AsyncMock()):
        for i in range(3):
            await Warns.warn.callback(cog, ctx, member, reason=f"r{i}")

    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.clear_warns.callback(cog, ctx, member)

    async with cog._db.execute("SELECT COUNT(*) FROM warns WHERE user_id = 110") as cur:
        (total,) = await cur.fetchone()
    assert total == 0


async def test_clearwarns_confirma_com_embed_verde(cog):
    member = make_member(id=120)
    ctx = make_ctx()

    with patch("cogs.warns.send_log", new=AsyncMock()):
        await Warns.clear_warns.callback(cog, ctx, member)

    embed = _embed(ctx)
    assert "limpos" in embed.title.lower()
