import asyncio
import logging
import os
import re
import time
import discord
from discord.ext import commands
import yt_dlp

log = logging.getLogger("cog.music")

# ── yt-dlp ────────────────────────────────────────────────────────────────
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

# Para extrair playlist inteira sem baixar áudio agora
YTDL_FLAT_OPTIONS = {
    **YTDL_OPTIONS,
    "noplaylist": False,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

CACHE_TTL = 3600      # 1 hora
CACHE_MAX = 100       # entradas máximas no cache
PLAYLIST_MAX = 200    # máximo de músicas por playlist

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
ytdl_flat = yt_dlp.YoutubeDL(YTDL_FLAT_OPTIONS)

# ── Detecção de URL ───────────────────────────────────────────────────────
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/(track|playlist|album)/([A-Za-z0-9]+)"
)
_YT_PLAYLIST_RE = re.compile(
    r"(?:youtube\.com|youtu\.be).*[?&]list=|youtube\.com/playlist"
)

# ── Spotipy (opcional) ────────────────────────────────────────────────────
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    _SPOTIPY_AVAILABLE = True
except ImportError:
    _SPOTIPY_AVAILABLE = False

_SP_ID = os.getenv("SPOTIPY_CLIENT_ID")
_SP_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")


def music_embed(title: str, description: str, color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


# ── Cache de busca ────────────────────────────────────────────────────────
class SearchCache:
    """Cache LRU simples com TTL para buscas do YouTube."""

    def __init__(self, ttl: int = CACHE_TTL, maxsize: int = CACHE_MAX):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict[str, tuple[dict, float]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: dict):
        if len(self._store) >= self._maxsize:
            oldest = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest]
        self._store[key] = (value, time.monotonic())


_search_cache = SearchCache()


# ── Estado por guild ──────────────────────────────────────────────────────
class GuildMusicState:
    def __init__(self):
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.loop: bool = False
        self.volume: float = 0.5
        self._inactivity_task: asyncio.Task | None = None
        self._preload_task: asyncio.Task | None = None
        self._preloaded: dict | None = None


# ── Cog principal ─────────────────────────────────────────────────────────
class Music(commands.Cog, name="Música"):
    """Comandos para reprodução de músicas via YouTube e Spotify."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = {}
        self._sp = None

        if _SPOTIPY_AVAILABLE and _SP_ID and _SP_SECRET:
            try:
                self._sp = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=_SP_ID, client_secret=_SP_SECRET
                    )
                )
                log.info("Integração com Spotify ativa.")
            except Exception as e:
                log.warning("Falha ao inicializar Spotify: %s", e)
        elif not _SPOTIPY_AVAILABLE:
            log.info("spotipy não instalado — Spotify desativado.")
        else:
            log.info("SPOTIPY_CLIENT_ID/SECRET ausentes — Spotify desativado.")

    def _state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildMusicState()
        return self._states[guild_id]

    # ── Detecção de tipo ──────────────────────────────────────────────────

    def _is_spotify(self, query: str) -> bool:
        return bool(_SPOTIFY_RE.match(query))

    def _is_yt_playlist(self, query: str) -> bool:
        return bool(_YT_PLAYLIST_RE.search(query))

    # ── Busca única (YouTube) ─────────────────────────────────────────────

    async def _search(self, query: str) -> dict | None:
        cache_key = query.lower().strip()
        cached = _search_cache.get(cache_key)
        if cached:
            log.debug("Cache hit: '%s'", query)
            return cached

        loop = asyncio.get_running_loop()
        search = query if query.startswith("http") else f"ytsearch:{query}"
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(search, download=False)
            )
        except yt_dlp.utils.DownloadError:
            return None

        if not data:
            return None
        info = data["entries"][0] if "entries" in data else data
        if not info:
            return None

        result = {
            "source": info["url"],
            "title": info.get("title", "Sem título"),
            "url": info.get("webpage_url", ""),
            "duration": info.get("duration") or 0,
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", "Desconhecido"),
            "_needs_fetch": False,
        }
        _search_cache.set(cache_key, result)
        return result

    # ── Extração de playlist YouTube ──────────────────────────────────────

    async def _extract_yt_playlist(self, url: str) -> list[dict]:
        """Retorna metadados de todos os vídeos de uma playlist do YouTube."""
        loop = asyncio.get_running_loop()

        def _fetch():
            data = ytdl_flat.extract_info(url, download=False)
            if not data:
                return []
            results = []
            for e in data.get("entries") or []:
                if not e:
                    continue
                vid_id = e.get("id") or ""
                vid_url = (
                    f"https://www.youtube.com/watch?v={vid_id}"
                    if vid_id and not vid_id.startswith("http")
                    else e.get("url", "")
                )
                thumbnails = e.get("thumbnails") or []
                thumbnail = thumbnails[-1].get("url", "") if thumbnails else e.get("thumbnail", "")
                results.append({
                    "title": e.get("title") or "Sem título",
                    "url": vid_url,
                    "duration": e.get("duration") or 0,
                    "thumbnail": thumbnail,
                    "uploader": e.get("uploader") or e.get("channel") or "YouTube",
                    "source": "",
                    "_needs_fetch": True,
                    "_query": vid_url,
                })
                if len(results) >= PLAYLIST_MAX:
                    break
            return results

        try:
            return await loop.run_in_executor(None, _fetch)
        except Exception as e:
            log.error("Erro ao extrair playlist YT: %s", e)
            return []

    # ── Extração de Spotify ───────────────────────────────────────────────

    async def _extract_spotify(self, url: str) -> list[dict]:
        """Converte um link do Spotify em uma lista de queries para busca no YouTube."""
        if not self._sp:
            return []

        match = _SPOTIFY_RE.match(url)
        if not match:
            return []
        resource_type = match.group(1)
        loop = asyncio.get_running_loop()

        def _fetch() -> list[str]:
            queries: list[str] = []
            try:
                if resource_type == "track":
                    t = self._sp.track(url)
                    queries.append(f"{t['name']} {t['artists'][0]['name']}")

                elif resource_type == "playlist":
                    page = self._sp.playlist_tracks(url, limit=100)
                    while page and len(queries) < PLAYLIST_MAX:
                        for item in page.get("items") or []:
                            track = item.get("track")
                            if not track or track.get("is_local"):
                                continue
                            queries.append(f"{track['name']} {track['artists'][0]['name']}")
                            if len(queries) >= PLAYLIST_MAX:
                                break
                        page = self._sp.next(page) if page.get("next") else None

                elif resource_type == "album":
                    page = self._sp.album_tracks(url, limit=50)
                    while page and len(queries) < PLAYLIST_MAX:
                        for item in page.get("items") or []:
                            queries.append(f"{item['name']} {item['artists'][0]['name']}")
                            if len(queries) >= PLAYLIST_MAX:
                                break
                        page = self._sp.next(page) if page.get("next") else None

            except Exception as e:
                log.error("Erro na API do Spotify: %s", e)
            return queries

        queries = await loop.run_in_executor(None, _fetch)
        return [{
            "title": q,
            "url": "",
            "duration": 0,
            "thumbnail": "",
            "uploader": "Spotify",
            "source": "",
            "_needs_fetch": True,
            "_query": q,
        } for q in queries]

    # ── Playback ──────────────────────────────────────────────────────────

    def _duration_fmt(self, seconds) -> str:
        if not seconds:
            return "??:??"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _schedule_preload(self, state: GuildMusicState):
        """Pré-aquece o cache para a próxima música da fila."""
        if state._preload_task and not state._preload_task.done():
            return
        if not state.queue:
            return

        async def _preload():
            next_song = state.queue[0]
            query = next_song.get("_query") or next_song.get("url") or next_song.get("title", "")
            if not query:
                return
            try:
                result = await self._search(query)
                if result and not next_song.get("_needs_fetch"):
                    state._preloaded = result
                log.debug("Pré-carregado: '%s'", (result or {}).get("title", ""))
            except Exception as e:
                log.debug("Erro no pré-carregamento: %s", e)

        state._preload_task = self.bot.loop.create_task(_preload())

    def _start_playing(self, ctx: commands.Context, song: dict):
        state = self._state(ctx.guild.id)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song["source"], **FFMPEG_OPTIONS),
            volume=state.volume,
        )
        ctx.voice_client.play(source, after=lambda _: self._play_next(ctx))

    async def _fetch_and_play(self, ctx: commands.Context, song: dict):
        """Resolve a URL de áudio de uma música lazy e inicia a reprodução."""
        query = song.get("_query") or song.get("url") or song.get("title", "")
        fetched = await self._search(query)
        if not fetched:
            await ctx.send(
                embed=music_embed(
                    "Pulando",
                    f"Não encontrei no YouTube: **{song['title']}**",
                    discord.Color.orange(),
                ),
                delete_after=8,
            )
            self._play_next(ctx)
            return
        song.update(fetched)
        song["_needs_fetch"] = False
        vc = ctx.voice_client
        if vc and not vc.is_playing() and not vc.is_paused():
            self._start_playing(ctx, song)

    def _play_next(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if state.loop and state.current:
            state.queue.insert(0, state.current)

        if not state.queue:
            state.current = None
            if state._inactivity_task:
                state._inactivity_task.cancel()
            state._inactivity_task = self.bot.loop.create_task(self._auto_disconnect(ctx))
            return

        # Usa pré-carregado se disponível e compatível
        next_song = state.queue[0]
        if (
            state._preloaded
            and not next_song.get("_needs_fetch")
            and state._preloaded.get("title") == next_song.get("title")
        ):
            state.current = state._preloaded
            state._preloaded = None
        else:
            state.current = next_song
        state.queue.pop(0)

        self._schedule_preload(state)

        if state.current.get("_needs_fetch"):
            self.bot.loop.create_task(self._fetch_and_play(ctx, state.current))
        else:
            self._start_playing(ctx, state.current)

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(120)
        vc = ctx.voice_client
        if vc and not vc.is_playing():
            await vc.disconnect()
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

    # ── Fila: adicionar uma ───────────────────────────────────────────────

    async def _enqueue_one(self, ctx: commands.Context, song: dict):
        if not ctx.voice_client and not await self._ensure_voice(ctx):
            return
        state = self._state(ctx.guild.id)
        song.setdefault("_query", song.get("url", song.get("title", "")))
        state.queue.append(song)

        if state._inactivity_task:
            state._inactivity_task.cancel()
            state._inactivity_task = None

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            self._play_next(ctx)
            embed = discord.Embed(title="Tocando agora", color=discord.Color.green())
        else:
            self._schedule_preload(state)
            embed = discord.Embed(title="Adicionado à fila", color=discord.Color.blurple())
            embed.add_field(name="Posição", value=str(len(state.queue)))

        url = song.get("url", "")
        embed.description = f"[{song['title']}]({url})" if url else song["title"]
        embed.add_field(name="Duração", value=self._duration_fmt(song.get("duration", 0)))
        embed.add_field(name="Canal", value=song.get("uploader", "?"))
        if song.get("thumbnail"):
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed)

    # ── Fila: adicionar várias ────────────────────────────────────────────

    async def _enqueue_many(self, ctx: commands.Context, songs: list[dict], source: str):
        if not ctx.voice_client and not await self._ensure_voice(ctx):
            return
        state = self._state(ctx.guild.id)
        already_playing = ctx.voice_client.is_playing() or ctx.voice_client.is_paused() or bool(state.current)

        for song in songs:
            state.queue.append(song)

        if state._inactivity_task:
            state._inactivity_task.cancel()
            state._inactivity_task = None

        capped = f" *(limitado a {PLAYLIST_MAX})*" if len(songs) >= PLAYLIST_MAX else ""
        embed = discord.Embed(
            title="🎵 Playlist adicionada à fila",
            description=f"**{len(songs)}** músicas de {source}{capped}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

        if not already_playing:
            self._play_next(ctx)

    # ── Reconexão automática ──────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            guild = member.guild
            state = self._states.get(guild.id)
            if not state or not state.current:
                return
            await asyncio.sleep(3)
            if guild.voice_client:
                return
            try:
                vc = await before.channel.connect()
                log.info("Reconectado a '%s' após desconexão inesperada.", before.channel.name)
                if state.current and not state.current.get("_needs_fetch"):
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(state.current["source"], **FFMPEG_OPTIONS),
                        volume=state.volume,
                    )
                    vc.play(source, after=lambda _: None)
            except Exception as e:
                log.warning("Falha ao reconectar à voz: %s", e)

    # ── Comandos ──────────────────────────────────────────────────────────

    @commands.command(name="join", aliases=["entrar"], help="Entra no seu canal de voz.")
    async def join(self, ctx: commands.Context):
        if await self._ensure_voice(ctx):
            await ctx.send(embed=music_embed("Conectado", f"Entrei em **{ctx.author.voice.channel.name}**."))

    @commands.command(name="m", aliases=["tocar"], help="Toca música, URL do YouTube ou link do Spotify (faixa/playlist/álbum).")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def play(self, ctx: commands.Context, *, query: str):
        if not await self._ensure_voice(ctx):
            return

        # ── Spotify ───────────────────────────────────────────────────────
        if self._is_spotify(query):
            if not self._sp:
                return await ctx.send(embed=music_embed(
                    "Spotify não configurado",
                    "Adicione `SPOTIPY_CLIENT_ID` e `SPOTIPY_CLIENT_SECRET` no arquivo `.env`.\n"
                    "Crie as credenciais em https://developer.spotify.com/dashboard",
                    discord.Color.red(),
                ))
            match = _SPOTIFY_RE.match(query)
            resource_type = match.group(1) if match else ""
            tipo_label = {"track": "faixa", "playlist": "playlist", "album": "álbum"}.get(resource_type, resource_type)

            msg = await ctx.send(embed=music_embed("Spotify 🎵", f"Carregando {tipo_label}...", discord.Color.green()))
            async with ctx.typing():
                songs = await self._extract_spotify(query)
            await msg.delete()

            if not songs:
                return await ctx.send(embed=music_embed("Erro", "Não encontrei nada nesse link do Spotify.", discord.Color.red()))

            if resource_type == "track":
                async with ctx.typing():
                    song = await self._search(songs[0]["_query"])
                if not song:
                    return await ctx.send(embed=music_embed("Erro", "Não encontrei essa faixa no YouTube.", discord.Color.red()))
                await self._enqueue_one(ctx, song)
            else:
                await self._enqueue_many(ctx, songs, f"Spotify ({tipo_label})")
            return

        # ── Playlist do YouTube ───────────────────────────────────────────
        if self._is_yt_playlist(query):
            msg = await ctx.send(embed=music_embed("YouTube Playlist 🎵", "Carregando playlist...", discord.Color.red()))
            async with ctx.typing():
                songs = await self._extract_yt_playlist(query)
            await msg.delete()

            if not songs:
                return await ctx.send(embed=music_embed("Erro", "Não consegui carregar essa playlist.", discord.Color.red()))
            await self._enqueue_many(ctx, songs, "YouTube Playlist")
            return

        # ── Música/URL única ──────────────────────────────────────────────
        async with ctx.typing():
            song = await self._search(query)
        if song is None:
            return await ctx.send(embed=music_embed("Erro", "Não consegui encontrar essa música.", discord.Color.red()))
        await self._enqueue_one(ctx, song)

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
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
            await ctx.send(embed=music_embed("Pulado", "Música pulada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está tocando.", discord.Color.orange()))

    @commands.command(name="stop", aliases=["parar"], help="Para a música e limpa a fila.")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def stop(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        state._preloaded = None
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
        url = song.get("url", "")
        embed = discord.Embed(
            title="Tocando agora",
            description=f"[{song['title']}]({url})" if url else song["title"],
            color=discord.Color.green(),
        )
        embed.add_field(name="Duração", value=self._duration_fmt(song.get("duration", 0)))
        embed.add_field(name="Canal", value=song.get("uploader", "?"))
        embed.add_field(name="Loop", value="Ativado" if state.loop else "Desativado")
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        if song.get("thumbnail"):
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["fila", "q"], help="Exibe a fila de músicas.")
    async def queue_cmd(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if not state.queue and not state.current:
            return await ctx.send(embed=music_embed("Fila vazia", "Nenhuma música na fila."))
        embed = discord.Embed(title="Fila de Músicas", color=discord.Color.blurple())
        if state.current:
            url = state.current.get("url", "")
            desc = f"[{state.current['title']}]({url})" if url else state.current["title"]
            embed.add_field(name="Tocando agora", value=desc, inline=False)
        if state.queue:
            lines = []
            for i, s in enumerate(state.queue[:10], 1):
                url = s.get("url", "")
                link = f"[{s['title']}]({url})" if url else s["title"]
                lines.append(f"`{i}.` {link} — {self._duration_fmt(s.get('duration', 0))}")
            if len(state.queue) > 10:
                lines.append(f"*...e mais {len(state.queue) - 10} músicas*")
            embed.add_field(name="Próximas", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Total na fila: {len(state.queue)} | Loop: {'On' if state.loop else 'Off'}")
        await ctx.send(embed=embed)

    @commands.command(name="loop", help="Ativa/desativa o loop da música atual.")
    async def loop_cmd(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.loop = not state.loop
        await ctx.send(embed=music_embed("Loop", f"Loop {'ativado' if state.loop else 'desativado'}."))

    @commands.command(name="clear", aliases=["limpar"], help="Limpa a fila sem parar a música.")
    async def clear_queue(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        state._preloaded = None
        await ctx.send(embed=music_embed("Fila limpa", "Todas as músicas da fila foram removidas."))

    @commands.command(name="remove", aliases=["remover"], help="Remove uma música da fila pelo número.")
    async def remove(self, ctx: commands.Context, index: int):
        state = self._state(ctx.guild.id)
        if not 1 <= index <= len(state.queue):
            return await ctx.send(embed=music_embed("Erro", "Posição inválida.", discord.Color.orange()))
        removed = state.queue.pop(index - 1)
        await ctx.send(embed=music_embed("Removido", f"**{removed['title']}** removido da fila."))

    @play.error
    @skip.error
    @stop.error
    async def music_cooldown_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                embed=music_embed("Devagar aí!", f"Aguarde {error.retry_after:.1f}s.", discord.Color.orange()),
                delete_after=5,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
