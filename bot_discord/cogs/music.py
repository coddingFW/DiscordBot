import asyncio
import logging
import discord
from discord.ext import commands
import yt_dlp

log = logging.getLogger("cog.music")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "extractaudio": True,
    "audioformat": "mp3",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


def music_embed(title: str, description: str, color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


class GuildMusicState:
    def __init__(self):
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.loop: bool = False
        self.volume: float = 0.5
        self._inactivity_task: asyncio.Task | None = None


class Music(commands.Cog, name="Música"):
    """Comandos para reprodução de músicas via YouTube."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = {}

    def _state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildMusicState()
        return self._states[guild_id]

    async def _search(self, query: str) -> dict | None:
        loop = asyncio.get_running_loop()
        search = query if query.startswith("http") else f"ytsearch:{query}"
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(search, download=False)
            )
        except yt_dlp.utils.DownloadError:
            return None

        if "entries" in data:
            info = data["entries"][0]
        else:
            info = data

        return {
            "source": info["url"],
            "title": info.get("title", "Sem título"),
            "url": info.get("webpage_url", ""),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", "Desconhecido"),
        }

    def _duration_fmt(self, seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _play_next(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if state.loop and state.current:
            state.queue.insert(0, state.current)

        if not state.queue:
            state.current = None
            if state._inactivity_task:
                state._inactivity_task.cancel()
            state._inactivity_task = self.bot.loop.create_task(
                self._auto_disconnect(ctx)
            )
            return

        state.current = state.queue.pop(0)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(state.current["source"], **FFMPEG_OPTIONS),
            volume=state.volume,
        )
        ctx.voice_client.play(source, after=lambda _: self._play_next(ctx))

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(120)
        if ctx.voice_client and not ctx.voice_client.is_playing():
            await ctx.voice_client.disconnect()
            await ctx.send(
                embed=music_embed("Desconectado", "Saí por inatividade (2 min).", discord.Color.greyple())
            )

    async def _ensure_voice(self, ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            await ctx.send(embed=music_embed("Erro", "Entre em um canal de voz primeiro.", discord.Color.red()))
            return False
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        return True

    @commands.command(name="join", aliases=["entrar"], help="Entra no seu canal de voz.")
    async def join(self, ctx: commands.Context):
        if await self._ensure_voice(ctx):
            await ctx.send(
                embed=music_embed("Conectado", f"Entrei em **{ctx.author.voice.channel.name}**.")
            )

    @commands.command(name="m", aliases=["tocar"], help="Toca uma música ou URL do YouTube.")
    async def play(self, ctx: commands.Context, *, query: str):
        if not await self._ensure_voice(ctx):
            return

        async with ctx.typing():
            song = await self._search(query)
            if song is None:
                return await ctx.send(
                    embed=music_embed("Erro", "Não consegui encontrar essa música.", discord.Color.red())
                )

        if not ctx.voice_client:
            if not await self._ensure_voice(ctx):
                return

        state = self._state(ctx.guild.id)
        state.queue.append(song)

        if state._inactivity_task:
            state._inactivity_task.cancel()
            state._inactivity_task = None

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            self._play_next(ctx)
            embed = discord.Embed(title="Tocando agora", color=discord.Color.green())
        else:
            embed = discord.Embed(title="Adicionado à fila", color=discord.Color.blurple())
            embed.add_field(name="Posição", value=str(len(state.queue)))

        embed.description = f"[{song['title']}]({song['url']})"
        embed.add_field(name="Duração", value=self._duration_fmt(song["duration"]))
        embed.add_field(name="Canal", value=song["uploader"])
        if song["thumbnail"]:
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed)

    @commands.command(name="pause", aliases=["pausar"], help="Pausa a música atual.")
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send(embed=music_embed("Pausado", "Música pausada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está tocando.", discord.Color.orange()))

    @commands.command(name="resume", aliases=["continuar"], help="Retoma a música pausada.")
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send(embed=music_embed("Retomado", "Música retomada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está pausado.", discord.Color.orange()))

    @commands.command(name="skip", aliases=["s", "pular"], help="Pula para a próxima música.")
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send(embed=music_embed("Pulado", "Música pulada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está tocando.", discord.Color.orange()))

    @commands.command(name="stop", aliases=["parar"], help="Para a música e limpa a fila.")
    async def stop(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send(embed=music_embed("Parado", "Fila limpa e bot desconectado.", discord.Color.red()))

    @commands.command(name="volume", aliases=["vol"], help="Ajusta o volume (0–100).")
    async def volume(self, ctx: commands.Context, vol: int):
        if not 0 <= vol <= 100:
            return await ctx.send(embed=music_embed("Erro", "O volume deve ser entre 0 e 100.", discord.Color.orange()))

        state = self._state(ctx.guild.id)
        state.volume = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = state.volume
        await ctx.send(embed=music_embed("Volume", f"Volume ajustado para **{vol}%**."))

    @commands.command(name="nowplaying", aliases=["np", "tocando"], help="Mostra a música atual.")
    async def nowplaying(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if not state.current:
            return await ctx.send(embed=music_embed("Nada tocando", "Nenhuma música no momento."))

        song = state.current
        embed = discord.Embed(
            title="Tocando agora",
            description=f"[{song['title']}]({song['url']})",
            color=discord.Color.green(),
        )
        embed.add_field(name="Duração", value=self._duration_fmt(song["duration"]))
        embed.add_field(name="Canal", value=song["uploader"])
        embed.add_field(name="Loop", value="Ativado" if state.loop else "Desativado")
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        if song["thumbnail"]:
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["fila", "q"], help="Exibe a fila de músicas.")
    async def queue_cmd(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if not state.queue and not state.current:
            return await ctx.send(embed=music_embed("Fila vazia", "Nenhuma música na fila."))

        embed = discord.Embed(title="Fila de Músicas", color=discord.Color.blurple())
        if state.current:
            embed.add_field(
                name="Tocando agora",
                value=f"[{state.current['title']}]({state.current['url']})",
                inline=False,
            )
        if state.queue:
            items = "\n".join(
                f"`{i}.` [{s['title']}]({s['url']}) — {self._duration_fmt(s['duration'])}"
                for i, s in enumerate(state.queue[:10], 1)
            )
            if len(state.queue) > 10:
                items += f"\n*...e mais {len(state.queue) - 10} músicas*"
            embed.add_field(name="Próximas", value=items, inline=False)
        embed.set_footer(text=f"Total na fila: {len(state.queue)} | Loop: {'On' if state.loop else 'Off'}")
        await ctx.send(embed=embed)

    @commands.command(name="loop", help="Ativa/desativa o loop da música atual.")
    async def loop_cmd(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.loop = not state.loop
        status = "ativado" if state.loop else "desativado"
        await ctx.send(embed=music_embed("Loop", f"Loop {status}."))

    @commands.command(name="clear", aliases=["limpar"], help="Limpa a fila sem parar a música.")
    async def clear_queue(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        await ctx.send(embed=music_embed("Fila limpa", "Todas as músicas da fila foram removidas."))

    @commands.command(name="remove", aliases=["remover"], help="Remove uma música da fila pelo número.")
    async def remove(self, ctx: commands.Context, index: int):
        state = self._state(ctx.guild.id)
        if not 1 <= index <= len(state.queue):
            return await ctx.send(embed=music_embed("Erro", "Posição inválida.", discord.Color.orange()))
        removed = state.queue.pop(index - 1)
        await ctx.send(embed=music_embed("Removido", f"**{removed['title']}** removido da fila."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
