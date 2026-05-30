"""Testes do cog de utilitários — sem Discord real."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.utility import Utility


def make_role(name="Membro"):
    role = MagicMock()
    role.mention = f"@{name}"
    role.name = name
    return role


def make_guild():
    guild = SimpleNamespace()
    guild.id = 1
    guild.name = "Servidor Teste"
    guild.icon = None
    guild.owner = SimpleNamespace(mention="<@1>")
    guild.member_count = 42
    guild.text_channels = [MagicMock(), MagicMock()]
    guild.voice_channels = [MagicMock()]
    guild.roles = [make_role("everyone"), make_role("Membro")]
    guild.created_at = MagicMock()
    guild.created_at.strftime = lambda fmt: "01/01/2020"
    guild.premium_tier = 1
    guild.premium_subscription_count = 3
    return guild


def make_member(bot_user=False):
    member = MagicMock()
    member.id = 123
    member.name = "usuario"
    member.display_name = "Usuario"
    member.mention = "<@123>"
    member.color = discord.Color.blurple()
    member.bot = bot_user
    member.roles = [make_role("everyone"), make_role("Membro")]
    member.display_avatar = SimpleNamespace(url="https://example.com/avatar.png")
    member.created_at = MagicMock()
    member.created_at.strftime = lambda fmt: "01/01/2022"
    member.joined_at = MagicMock()
    member.joined_at.strftime = lambda fmt: "01/06/2022"
    member.__str__ = lambda s: "usuario#0001"
    return member


def make_bot(guilds=None):
    bot = MagicMock()
    bot.guilds = guilds or [MagicMock()]
    bot.guilds[0].member_count = 10
    bot.command_prefix = "!"
    bot.latency = 0.05
    bot.user = MagicMock()
    bot.user.name = "Good Vibes"
    bot.user.display_avatar = MagicMock()
    bot.user.display_avatar.url = "https://example.com/bot.png"
    return bot


def make_ctx(guild=None, author=None, bot=None):
    ctx = MagicMock()
    ctx.guild = guild or make_guild()
    ctx.author = author or make_member()
    ctx.bot = bot or make_bot()
    ctx.send = AsyncMock()
    ctx.message = MagicMock()
    ctx.message.delete = AsyncMock()
    return ctx


@pytest.fixture
def cog():
    return Utility(bot=make_bot())


# ── ping ──────────────────────────────────────────────────────────────────────

async def test_ping_responde(cog):
    ctx = make_ctx()
    cog.bot.latency = 0.05
    await Utility.ping.callback(cog, ctx)
    ctx.send.assert_called_once()
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Pong" in embed.title


async def test_ping_cor_verde_baixa_latencia(cog):
    ctx = make_ctx()
    cog.bot.latency = 0.05  # 50ms → verde
    await Utility.ping.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.color == discord.Color.green()


async def test_ping_cor_laranja_media_latencia(cog):
    ctx = make_ctx()
    cog.bot.latency = 0.15  # 150ms → laranja
    await Utility.ping.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.color == discord.Color.orange()


async def test_ping_cor_vermelha_alta_latencia(cog):
    ctx = make_ctx()
    cog.bot.latency = 0.25  # 250ms → vermelho
    await Utility.ping.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.color == discord.Color.red()


# ── uptime ────────────────────────────────────────────────────────────────────

async def test_uptime_responde(cog):
    ctx = make_ctx()
    await Utility.uptime.callback(cog, ctx)
    ctx.send.assert_called_once()
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Uptime" in embed.title


async def test_uptime_contem_tempo(cog):
    ctx = make_ctx()
    await Utility.uptime.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Online há" in embed.description


# ── serverinfo ────────────────────────────────────────────────────────────────

async def test_serverinfo_exibe_nome_servidor(cog):
    guild = make_guild()
    ctx = make_ctx(guild=guild)
    await Utility.serverinfo.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Servidor Teste"


async def test_serverinfo_exibe_membros(cog):
    guild = make_guild()
    ctx = make_ctx(guild=guild)
    await Utility.serverinfo.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    fields = {f.name: f.value for f in embed.fields}
    assert "Membros" in fields
    assert str(42) in str(fields["Membros"])


# ── userinfo ─────────────────────────────────────────────────────────────────

async def test_userinfo_exibe_nome(cog):
    member = make_member()
    ctx = make_ctx(author=member)
    await Utility.userinfo.callback(cog, ctx, member=member)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "usuario" in embed.title.lower()


async def test_userinfo_sem_membro_usa_autor(cog):
    member = make_member()
    ctx = make_ctx(author=member)
    await Utility.userinfo.callback(cog, ctx, member=None)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed is not None


# ── avatar ────────────────────────────────────────────────────────────────────

async def test_avatar_responde(cog):
    member = make_member()
    ctx = make_ctx(author=member)
    await Utility.avatar.callback(cog, ctx, member=member)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert "Avatar" in embed.title


async def test_avatar_sem_membro_usa_autor(cog):
    member = make_member()
    ctx = make_ctx(author=member)
    await Utility.avatar.callback(cog, ctx, member=None)
    ctx.send.assert_called_once()


# ── botinfo ───────────────────────────────────────────────────────────────────

async def test_botinfo_exibe_nome_bot(cog):
    ctx = make_ctx()
    await Utility.botinfo.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Good Vibes"


async def test_botinfo_exibe_servidores(cog):
    ctx = make_ctx()
    await Utility.botinfo.callback(cog, ctx)
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    fields = {f.name: f.value for f in embed.fields}
    assert "Servidores" in fields


# ── say ───────────────────────────────────────────────────────────────────────

async def test_say_envia_mensagem(cog):
    ctx = make_ctx()
    await Utility.say.callback(cog, ctx, message="Olá mundo")
    ctx.message.delete.assert_called_once()
    ctx.send.assert_called_once_with("Olá mundo")


# ── embed ─────────────────────────────────────────────────────────────────────

async def test_send_embed_cria_embed(cog):
    ctx = make_ctx()
    await Utility.send_embed.callback(cog, ctx, title="Título", description="Descrição")
    ctx.message.delete.assert_called_once()
    embed = ctx.send.call_args.kwargs.get("embed") or ctx.send.call_args.args[0]
    assert embed.title == "Título"
    assert embed.description == "Descrição"
