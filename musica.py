# music_player.py
import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot  # Armazena a instância do bot
        self.song_queues = {}  # Dicionário para armazenar filas de músicas por servidor

    def get_queue(self, guild_id):
        """Retorna a fila de músicas de um servidor específico."""
        if guild_id not in self.song_queues:
            self.song_queues[guild_id] = []
        return self.song_queues[guild_id]

    async def join(self, ctx):
        try:
            if ctx.author.voice is None:
                await ctx.send("Você precisa estar em um canal de voz para chamar o bot!")
                return

            voice_channel = ctx.author.voice.channel

            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect()

            await voice_channel.connect()
            await ctx.send(f'Conectado ao canal de voz: {voice_channel.name}')
        except discord.Forbidden:
            await ctx.send("Não tenho permissão para me conectar ao canal de voz.")
        except discord.HTTPException as e:
            await ctx.send(f"Erro ao conectar ao canal de voz: {str(e)}")
        except Exception as e:
            await ctx.send(f"Ocorreu um erro inesperado: {str(e)}")
            print(f"Erro inesperado: {str(e)}")

    async def play(self, ctx, *, query):
        try:
            if ctx.author.voice is None:
                await ctx.send("Você precisa estar em um canal de voz para tocar música!")
                return

            voice_channel = ctx.author.voice.channel

            if ctx.voice_client is None:
                vc = await voice_channel.connect()
            else:
                vc = ctx.voice_client

            await ctx.send(f'Buscando: {query}')
            with youtube_dl.YoutubeDL({'format': 'bestaudio'}) as ydl:
                info = ydl.extract_info(f"ytsearch:{query.lower()}", download=False)
                if 'entries' in info and len(info['entries']) > 0:
                    info = info['entries'][0]
                    URL = info['url']
                    title = info['title']
                    link = info['webpage_url']  # Link da música no YouTube
                    queue = self.get_queue(ctx.guild.id)
                    queue.append((URL, title, link))
                    await ctx.send(f'Adicionado à fila: **{title}**\nLink: {link}')
                    if not vc.is_playing():
                        self.play_next(vc, ctx)
                else:
                    await ctx.send("Nenhum resultado encontrado para a busca.")
        except Exception as e:
            await ctx.send(f"Erro ao buscar a música: {str(e)}")

    async def play_url(self, ctx, url):
        try:
            if ctx.author.voice is None:
                await ctx.send("Você precisa estar em um canal de voz para tocar música!")
                return

            voice_channel = ctx.author.voice.channel

            if ctx.voice_client is None:
                vc = await voice_channel.connect()
            else:
                vc = ctx.voice_client

            await ctx.send(f'Reproduzindo a partir do URL: {url}')
            with youtube_dl.YoutubeDL({'format': 'bestaudio'}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None or 'url' not in info:
                    raise Exception("Nenhum resultado encontrado para a busca.")
                URL = info['url']
                title = info['title']
                link = info['webpage_url']  # Link da música no YouTube
                queue = self.get_queue(ctx.guild.id)
                queue.append((URL, title, link))
                await ctx.send(f'Adicionado à fila: **{title}**\nLink: {link}')
                if not vc.is_playing():
                    self.play_next(vc, ctx)
        except Exception as e:
            await ctx.send(f"Erro ao buscar a música: {str(e)}. Tentando buscar pelo nome.")
            await self.play(ctx, query=url)  # Tentar buscar pelo nome se o link falhar

    def play_next(self, vc, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            URL, title, link = queue.pop(0)
            vc.play(discord.FFmpegPCMAudio(URL), after=lambda e: self.check_queue(vc, ctx) if e else None)
            asyncio.run_coroutine_threadsafe(ctx.send(f'Tocando: **{title}**'), self.bot.loop)
        else:
            asyncio.create_task(self.disconnect_after_timeout(vc, ctx))

    async def fila(self, ctx):
        queue = self.get_queue(ctx.guild.id)
        if queue:
            msg = "Fila de músicas:\n"
            for i, (url, title, link) in enumerate(queue, 1):
                msg += f"{i}. **{title}**\nLink: {link}\n"
            await ctx.send(msg)
        else:
            await ctx.send("A fila está vazia.")

    async def pular(self, ctx):
        if ctx.voice_client is not None and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Pulando para a próxima música...")
            self.play_next(ctx.voice_client, ctx)
        else:
            await ctx.send("Não há música tocando no momento.")

    def check_queue(self, vc, ctx):
        if not vc.is_playing():
            self.play_next(vc, ctx)

    async def disconnect_after_timeout(self, vc, ctx):
        await asyncio.sleep(60)  # Espera 60 segundos
        if vc.is_connected() and not vc.is_playing():  # Verifica se está conectado e não está tocando
            await ctx.send("Acabaram as músicas! Tchau!")
            await vc.disconnect()
            self.clear_cache(ctx.guild.id)  # Limpa o cache quando a fila acabar

    async def stop(self, ctx):
        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect()
            self.clear_cache(ctx.guild.id)  # Limpa o cache ao parar o bot

    def clear_cache(self, guild_id):
        """Limpa a fila de músicas e libera recursos."""
        if guild_id in self.song_queues:
            self.song_queues[guild_id].clear()
            print(f"Cache limpo para o servidor {guild_id}: fila de músicas e recursos liberados.")

    def __del__(self):
        """Destrutor para garantir que os recursos sejam liberados."""
        for guild_id in self.song_queues:
            self.clear_cache(guild_id)