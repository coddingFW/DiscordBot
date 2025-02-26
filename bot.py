# main.py
import discord
from discord.ext import commands
from musica import MusicPlayer  # Importando a classe MusicPlayer

TOKEN='***TOKEN_REMOVIDO***'
intents = discord.Intents.default()
intents.message_content = True

# Inicialização do bot
bot = commands.Bot(command_prefix='!', intents=intents)
music_player = MusicPlayer(bot)  # Passando a instân do bot para a classe MusicPlayer

# Comandos do bot
@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} está online!')

@bot.command()
async def join(ctx):
    await music_player.join(ctx)

@bot.command()
async def play(ctx, *, query):
    await music_player.play(ctx, query=query)

@bot.command()
async def play_url(ctx, url):
    await music_player.play_url(ctx, url)

@bot.command()
async def fila(ctx):
    await music_player.fila(ctx)

@bot.command()
async def pular(ctx):
    await music_player.pular(ctx)

@bot.command()
async def stop(ctx):
    await music_player.stop(ctx)

# Executar o bot
bot.run(TOKEN)