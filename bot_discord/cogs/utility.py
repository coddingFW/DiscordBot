import time
import platform
import logging
import discord
from discord.ext import commands

log = logging.getLogger("cog.utility")

_START_TIME = time.time()


def util_embed(title: str, color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, color=color)


class Utility(commands.Cog, name="Utilitários"):
    """Comandos de informação e utilidade geral."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping", help="Mostra a latência do bot.")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000)
        color = discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 200 else discord.Color.red()
        embed = discord.Embed(title="Pong!", description=f"Latência: **{latency}ms**", color=color)
        await ctx.send(embed=embed)

    @commands.command(name="uptime", help="Mostra há quanto tempo o bot está online.")
    async def uptime(self, ctx: commands.Context):
        elapsed = int(time.time() - _START_TIME)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        embed = discord.Embed(
            title="Uptime",
            description=f"Online há **{h}h {m}m {s}s**",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", aliases=["servidor"], help="Informações do servidor.")
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        g = ctx.guild
        embed = discord.Embed(title=g.name, color=discord.Color.blurple())
        embed.set_thumbnail(url=g.icon.url if g.icon else discord.Embed.Empty)
        embed.add_field(name="Dono", value=g.owner.mention)
        embed.add_field(name="Membros", value=g.member_count)
        embed.add_field(name="Canais de texto", value=len(g.text_channels))
        embed.add_field(name="Canais de voz", value=len(g.voice_channels))
        embed.add_field(name="Cargos", value=len(g.roles))
        embed.add_field(name="Criado em", value=g.created_at.strftime("%d/%m/%Y"))
        embed.add_field(name="Nível de boost", value=g.premium_tier)
        embed.add_field(name="Boosts", value=g.premium_subscription_count)
        embed.set_footer(text=f"ID: {g.id}")
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", aliases=["usuario", "perfil"], help="Informações de um usuário.")
    @commands.guild_only()
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        roles = [r.mention for r in member.roles[1:]] or ["Nenhum"]
        embed = discord.Embed(title=str(member), color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Apelido", value=member.display_name)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="Conta criada", value=member.created_at.strftime("%d/%m/%Y"), inline=False)
        embed.add_field(name="Entrou no servidor", value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?")
        embed.add_field(name="Bot", value="Sim" if member.bot else "Não")
        embed.add_field(name=f"Cargos ({len(member.roles) - 1})", value=" ".join(roles[:10]), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="avatar", help="Exibe o avatar de um usuário.")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"Avatar de {member.display_name}", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="botinfo", aliases=["sobre"], help="Informações sobre o bot.")
    async def botinfo(self, ctx: commands.Context):
        embed = discord.Embed(title=self.bot.user.name, color=discord.Color.blurple())
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Servidores", value=len(self.bot.guilds))
        embed.add_field(name="Usuários", value=sum(g.member_count for g in self.bot.guilds))
        embed.add_field(name="Prefixo", value=self.bot.command_prefix)
        embed.add_field(name="Python", value=platform.python_version())
        embed.add_field(name="discord.py", value=discord.__version__)
        embed.add_field(name="Latência", value=f"{round(self.bot.latency * 1000)}ms")
        await ctx.send(embed=embed)

    @commands.command(name="say", help="Faz o bot enviar uma mensagem no canal.")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: commands.Context, *, message: str):
        await ctx.message.delete()
        await ctx.send(message)

    @commands.command(name="embed", help="Envia uma mensagem formatada como embed.")
    @commands.has_permissions(manage_messages=True)
    async def send_embed(self, ctx: commands.Context, title: str, *, description: str):
        await ctx.message.delete()
        await ctx.send(embed=discord.Embed(title=title, description=description, color=discord.Color.blurple()))


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
