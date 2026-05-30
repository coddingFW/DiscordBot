"""Testes do cog de moderação — sem Discord real, ctx e guild mockados."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.moderation import Moderation


def make_member(id=1, name="alvo", display_name="Alvo"):
    m = MagicMock(spec=discord.Member)
    m.id = id
    m.name = name
    m.display_name = display_name
    m.mention = f"<@{id}>"
    m.roles = []
    m.kick = AsyncMock()
    m.ban = AsyncMock()
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    m.send = AsyncMock()
    return m


def make_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.name = "Servidor Teste"
    guild.roles = []
    guild.channels = []
    guild.text_channels = []
    guild.create_role = AsyncMock(return_value=MagicMock(name="Muted"))
    guild.unban = AsyncMock()
    guild.bans = MagicMock()
    return guild


def make_ctx(guild=None):
    ctx = MagicMock()
    ctx.guild = guild or make_guild()
    ctx.author = MagicMock()
    ctx.author.id = 999
    ctx.author.__str__ = lambda s: "Mod#0001"
    ctx.send = AsyncMock()
    ctx.channel = MagicMock()
    ctx.channel.purge = AsyncMock(return_value=[MagicMock()] * 6)
    ctx.message = MagicMock()
    ctx.message.delete = AsyncMock()
    return ctx


@pytest.fixture
def cog():
    return Moderation(bot=None)


# ── kick ──────────────────────────────────────────────────────────────────────

async def test_kick_expulsa_membro(cog):
    member = make_member()
    ctx = make_ctx()
    with patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.kick.callback(cog, ctx, member, reason="teste")
    member.kick.assert_called_once_with(reason="teste")


async def test_kick_envia_embed(cog):
    member = make_member()
    ctx = make_ctx()
    with patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.kick.callback(cog, ctx, member, reason="spam")
    ctx.send.assert_called_once()
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Expulso" in embed.title


# ── ban ───────────────────────────────────────────────────────────────────────

async def test_ban_bane_membro(cog):
    member = make_member()
    ctx = make_ctx()
    with patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.ban.callback(cog, ctx, member, reason="flood")
    member.ban.assert_called_once_with(reason="flood")


async def test_ban_envia_embed(cog):
    member = make_member()
    ctx = make_ctx()
    with patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.ban.callback(cog, ctx, member, reason="flood")
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Banido" in embed.title


# ── unban ─────────────────────────────────────────────────────────────────────

async def test_unban_por_id(cog):
    guild = make_guild()
    user = MagicMock()
    user.id = 42
    user.name = "fulano"
    user.discriminator = "0000"
    entry = MagicMock()
    entry.user = user

    async def fake_bans():
        yield entry

    guild.bans.return_value = fake_bans()
    ctx = make_ctx(guild=guild)

    with patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.unban.callback(cog, ctx, identifier="42")
    guild.unban.assert_called_once_with(user)


async def test_unban_nao_encontrado(cog):
    guild = make_guild()

    async def fake_bans():
        return
        yield  # torna generator vazio

    guild.bans.return_value = fake_bans()
    ctx = make_ctx(guild=guild)
    await Moderation.unban.callback(cog, ctx, identifier="9999")
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Erro"


# ── purge ─────────────────────────────────────────────────────────────────────

async def test_purge_apaga_mensagens(cog):
    ctx = make_ctx()
    ctx.channel.purge = AsyncMock(return_value=[MagicMock()] * 6)
    msg_mock = AsyncMock()
    msg_mock.delete = AsyncMock()
    ctx.send = AsyncMock(return_value=msg_mock)
    await Moderation.purge.callback(cog, ctx, amount=5)
    ctx.channel.purge.assert_called_once_with(limit=6)


async def test_purge_quantidade_invalida(cog):
    ctx = make_ctx()
    await Moderation.purge.callback(cog, ctx, amount=0)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Erro"

    await Moderation.purge.callback(cog, ctx, amount=101)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Erro"


# ── mute ──────────────────────────────────────────────────────────────────────

async def test_mute_adiciona_cargo(cog):
    guild = make_guild()
    muted_role = MagicMock()
    muted_role.name = "Muted"
    guild.roles = [muted_role]

    member = make_member()
    member.roles = []
    ctx = make_ctx(guild=guild)

    with patch("discord.utils.get", return_value=muted_role), \
         patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.mute.callback(cog, ctx, member, reason="barulho")

    member.add_roles.assert_called_once_with(muted_role, reason="barulho")


async def test_mute_ja_silenciado(cog):
    guild = make_guild()
    muted_role = MagicMock()
    muted_role.name = "Muted"

    member = make_member()
    member.roles = [muted_role]
    ctx = make_ctx(guild=guild)

    with patch("discord.utils.get", return_value=muted_role):
        await Moderation.mute.callback(cog, ctx, member, reason="teste")

    member.add_roles.assert_not_called()
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "já está" in embed.description


# ── unmute ────────────────────────────────────────────────────────────────────

async def test_unmute_remove_cargo(cog):
    guild = make_guild()
    muted_role = MagicMock()
    muted_role.name = "Muted"

    member = make_member()
    member.roles = [muted_role]
    ctx = make_ctx(guild=guild)

    with patch("discord.utils.get", return_value=muted_role), \
         patch("cogs.moderation.send_log", new=AsyncMock()):
        await Moderation.unmute.callback(cog, ctx, member)

    member.remove_roles.assert_called_once_with(muted_role)


async def test_unmute_nao_silenciado(cog):
    guild = make_guild()
    member = make_member()
    member.roles = []
    ctx = make_ctx(guild=guild)

    with patch("discord.utils.get", return_value=None):
        await Moderation.unmute.callback(cog, ctx, member)

    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "não está" in embed.description
