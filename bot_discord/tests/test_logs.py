"""Testes do cog de logs — log_embed e send_log."""
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.logs import log_embed, send_log, Logs


# ── log_embed ─────────────────────────────────────────────────────────────────

def test_log_embed_titulo_e_cor():
    embed = log_embed("Teste", discord.Color.red())
    assert embed.title == "Teste"
    assert embed.color == discord.Color.red()


def test_log_embed_campos():
    embed = log_embed("Ação", discord.Color.green(), Usuário="João", Motivo="spam")
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Usuário"] == "João"
    assert fields["Motivo"] == "spam"


def test_log_embed_sem_campos():
    embed = log_embed("Vazio", discord.Color.blurple())
    assert len(embed.fields) == 0


# ── send_log ──────────────────────────────────────────────────────────────────

async def test_send_log_envia_quando_canal_existe():
    canal = MagicMock()
    canal.send = AsyncMock()
    canal.name = "logs"

    guild = MagicMock()
    guild.text_channels = [canal]

    embed = log_embed("Teste", discord.Color.red())

    with patch("discord.utils.get", return_value=canal):
        await send_log(guild, embed)

    canal.send.assert_called_once_with(embed=embed)


async def test_send_log_silencioso_sem_canal():
    guild = MagicMock()
    guild.text_channels = []

    embed = log_embed("Teste", discord.Color.red())

    with patch("discord.utils.get", return_value=None):
        await send_log(guild, embed)  # não deve lançar exceção


async def test_send_log_ignora_forbidden():
    canal = MagicMock()
    canal.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "sem permissão"))
    canal.name = "logs"

    guild = MagicMock()
    guild.text_channels = [canal]

    embed = log_embed("Teste", discord.Color.red())

    with patch("discord.utils.get", return_value=canal):
        await send_log(guild, embed)  # não deve lançar exceção


# ── listeners ─────────────────────────────────────────────────────────────────

async def test_on_member_join_envia_log():
    cog = Logs(bot=None)

    canal = MagicMock()
    canal.send = AsyncMock()

    guild = MagicMock()
    guild.text_channels = [canal]

    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.guild = guild
    member.created_at = MagicMock()
    member.created_at.timestamp = lambda: 1700000000.0
    member.__str__ = lambda s: "usuario#0001"

    with patch("discord.utils.get", return_value=canal):
        await cog.on_member_join(member)

    canal.send.assert_called_once()


async def test_on_message_delete_ignora_bot():
    cog = Logs(bot=None)

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = True

    await cog.on_message_delete(message)
    # não deve tentar enviar log


async def test_on_message_delete_ignora_sem_conteudo():
    cog = Logs(bot=None)

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = MagicMock()
    message.content = ""

    await cog.on_message_delete(message)


async def test_on_message_delete_envia_log():
    cog = Logs(bot=None)

    canal = MagicMock()
    canal.send = AsyncMock()

    guild = MagicMock()
    guild.text_channels = [canal]

    author = MagicMock()
    author.bot = False
    author.id = 1
    author.__str__ = lambda s: "user#0001"

    channel = MagicMock()
    channel.name = "geral"

    message = MagicMock(spec=discord.Message)
    message.author = author
    message.guild = guild
    message.content = "mensagem deletada"
    message.channel = channel

    with patch("discord.utils.get", return_value=canal):
        await cog.on_message_delete(message)

    canal.send.assert_called_once()
