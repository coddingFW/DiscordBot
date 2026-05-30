import asyncio
import json
import logging
import os
import random
import re
import time
import aiohttp
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
# SoundCloud: qualquer URL do soundcloud; "/sets/" indica playlist/álbum.
_SOUNDCLOUD_RE = re.compile(r"https?://(?:www\.|on\.|m\.)?soundcloud\.com/")
_SOUNDCLOUD_SET_RE = re.compile(r"https?://(?:www\.|m\.)?soundcloud\.com/[^/]+/sets/")

# ── Spotipy (opcional) ────────────────────────────────────────────────────
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    _SPOTIPY_AVAILABLE = True
except ImportError:
    _SPOTIPY_AVAILABLE = False

_SP_ID = os.getenv("SPOTIPY_CLIENT_ID")
_SP_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

# Headers para o scraping do Spotify (página pública /embed/)
_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _find_first(obj, key: str):
    """Busca recursiva pela primeira chave `key` em uma estrutura JSON."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _find_first(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_first(item, key)
            if result is not None:
                return result
    return None


def music_embed(title: str, description: str, color=discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


# ── Painel de controle interativo ─────────────────────────────────────────
class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        # Sincroniza estado do botão loop ao criar
        self._sync_loop_button()

    def _sync_loop_button(self):
        state = self.cog._state(self.guild_id)
        btn = discord.utils.get(self.children, callback=self.toggle_loop.callback)
        if btn is None:
            return
        if state.loop:
            btn.style = discord.ButtonStyle.success
            btn.label = "Song"
        elif state.loop_queue:
            btn.style = discord.ButtonStyle.primary
            btn.label = "Queue"
        else:
            btn.style = discord.ButtonStyle.secondary
            btn.label = None

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("Não estou em nenhum canal de voz.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            button.emoji = "▶️"
        elif vc.is_paused():
            vc.resume()
            button.emoji = "⏸"
        else:
            return await interaction.response.send_message("Nada tocando.", ephemeral=True)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭ Pulando...", ephemeral=True, delete_after=2)
        else:
            await interaction.response.send_message("Nada tocando.", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog._state(self.guild_id)
        if not state.queue:
            return await interaction.response.send_message("A fila está vazia.", ephemeral=True)
        random.shuffle(state.queue)
        await interaction.response.send_message(f"🔀 Fila embaralhada! ({len(state.queue)} músicas)", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cicla entre: sem loop → loop da música → loop da fila → sem loop."""
        state = self.cog._state(self.guild_id)
        if not state.loop and not state.loop_queue:
            state.loop = True
            state.loop_queue = False
            button.style = discord.ButtonStyle.success
            button.label = "Song"
        elif state.loop and not state.loop_queue:
            state.loop = False
            state.loop_queue = True
            button.style = discord.ButtonStyle.primary
            button.label = "Queue"
        else:
            state.loop = False
            state.loop_queue = False
            button.style = discord.ButtonStyle.secondary
            button.label = None
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏹", style=discord.ButtonStyle.danger)
    async def stop_music(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog._state(self.guild_id)
        state.queue.clear()
        state.current = None
        state.control_message = None
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
        self.stop()
        await interaction.response.edit_message(view=None)


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
        self.loop: bool = False        # loop da música atual
        self.loop_queue: bool = False  # loop da fila inteira
        self.volume: float = 0.5
        self._started_at: float | None = None  # monotonic timestamp do início da faixa
        self._inactivity_task: asyncio.Task | None = None
        self._preload_task: asyncio.Task | None = None
        self._preloaded: dict | None = None
        self.control_message: discord.Message | None = None
        self.control_ctx: "commands.Context | None" = None


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

    def _is_soundcloud(self, query: str) -> bool:
        return bool(_SOUNDCLOUD_RE.match(query))

    def _is_soundcloud_set(self, query: str) -> bool:
        return bool(_SOUNDCLOUD_SET_RE.match(query))

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

    # ── Extração de playlist (YouTube / SoundCloud) ───────────────────────

    async def _extract_playlist(self, url: str) -> list[dict]:
        """Retorna metadados de todas as faixas de uma playlist (YouTube ou SoundCloud)."""
        loop = asyncio.get_running_loop()

        def _fetch():
            data = ytdl_flat.extract_info(url, download=False)
            if not data:
                return []
            results = []
            for e in data.get("entries") or []:
                if not e:
                    continue
                # Prefere a URL completa do item (SoundCloud já traz o permalink);
                # senão, monta a URL do YouTube a partir do id do vídeo.
                vid_url = e.get("url") or ""
                vid_id = e.get("id") or ""
                if not vid_url.startswith("http") and vid_id:
                    vid_url = f"https://www.youtube.com/watch?v={vid_id}"
                if not vid_url:
                    continue
                thumbnails = e.get("thumbnails") or []
                thumbnail = thumbnails[-1].get("url", "") if thumbnails else e.get("thumbnail", "")
                results.append({
                    "title": e.get("title") or "Sem título",
                    "url": vid_url,
                    "duration": e.get("duration") or 0,
                    "thumbnail": thumbnail,
                    "uploader": e.get("uploader") or e.get("channel") or "Desconhecido",
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
            log.error("Erro ao extrair playlist: %s", e)
            return []

    # ── Extração de Spotify ───────────────────────────────────────────────

    async def _extract_spotify(self, url: str) -> list[dict]:
        """Converte um link do Spotify em uma lista de queries para busca no YouTube.

        Tenta a API oficial primeiro. Se falhar (403, sem credenciais, etc.),
        cai para o scraping da página pública /embed/.
        """
        match = _SPOTIFY_RE.match(url)
        if not match:
            return []
        resource_type = match.group(1)
        resource_id = match.group(2)

        queries: list[str] = []

        # 1) Tenta API oficial
        if self._sp:
            try:
                queries = await self._spotify_via_api(url, resource_type)
            except Exception as e:
                log.warning("API do Spotify falhou (%s) — caindo para scraping.", e)

        # 2) Fallback: scraping da página pública
        if not queries:
            try:
                queries = await self._spotify_via_scrape(resource_type, resource_id)
            except Exception as e:
                log.error("Scraping do Spotify falhou: %s", e)
                raise RuntimeError(f"Não consegui ler a playlist do Spotify: {e}")

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

    async def _spotify_via_api(self, url: str, resource_type: str) -> list[str]:
        """Extrai queries via API oficial do Spotify (requer Premium no app owner)."""
        loop = asyncio.get_running_loop()

        def _fetch() -> list[str]:
            queries: list[str] = []

            if resource_type == "track":
                t = self._sp.track(url)
                queries.append(f"{t['name']} {t['artists'][0]['name']}")

            elif resource_type == "playlist":
                # playlist_items substitui playlist_tracks no spotipy >= 2.22
                page = self._sp.playlist_items(
                    url, limit=100, additional_types=("track",)
                )
                while page and len(queries) < PLAYLIST_MAX:
                    for item in page.get("items") or []:
                        track = item.get("track")
                        if not track or track.get("is_local"):
                            continue
                        # Ignora episódios de podcast
                        if track.get("type") != "track":
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

            return queries

        try:
            queries = await loop.run_in_executor(None, _fetch)
        except Exception as e:
            log.error("Erro na API do Spotify: %s", e)
            raise  # propaga para o play() mostrar a mensagem de erro real

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

    def _progress_bar(self, elapsed: float, total: float, width: int = 16) -> str:
        """Gera barra de progresso: ▓▓▓▓░░░░ 1:23 / 3:45"""
        if not total or total <= 0:
            return "░" * width
        ratio = min(elapsed / total, 1.0)
        filled = int(ratio * width)
        bar = "▓" * filled + "░" * (width - filled)
        return f"{bar} `{self._duration_fmt(elapsed)} / {self._duration_fmt(total)}`"

    def _schedule_preload(self, state: GuildMusicState):
        """Pré-aquece o cache para a próxima música da fila."""
        if state._preload_task and not state._preload_task.done():
            return
        if not state.queue:
            return

        async def _preload():
            next_song = state.queue[0]
            # Música não-lazy já está resolvida — nada a fazer.
            if not next_song.get("_needs_fetch"):
                return
            query = next_song.get("_query") or next_song.get("url") or next_song.get("title", "")
            if not query:
                return
            try:
                result = await self._search(query)
                if result:
                    # Resolve a próxima faixa no próprio objeto da fila,
                    # eliminando o gap quando ela virar a atual.
                    next_song.update(result)
                    next_song["_needs_fetch"] = False
                    log.debug("Pré-carregado: '%s'", result.get("title", ""))
            except Exception as e:
                log.debug("Erro no pré-carregamento: %s", e)

        state._preload_task = self.bot.loop.create_task(_preload())

    def _start_playing(self, ctx: commands.Context, song: dict):
        state = self._state(ctx.guild.id)
        state._started_at = time.monotonic()
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song["source"], **FFMPEG_OPTIONS),
            volume=state.volume,
        )
        ctx.voice_client.play(source, after=lambda _: self._play_next(ctx))
        self.bot.loop.create_task(self._update_control_panel(ctx, song))

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
            self._start_playing(ctx, song)  # _start_playing já chama _update_control_panel

    def _play_next(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if state.loop and state.current:
            state.queue.insert(0, state.current)
        elif state.loop_queue and state.current:
            state.queue.append(state.current)  # adiciona ao final para loop da fila

        if not state.queue:
            state.current = None
            if state._inactivity_task:
                state._inactivity_task.cancel()
            state._inactivity_task = self.bot.loop.create_task(self._auto_disconnect(ctx))
            self.bot.loop.create_task(self._update_control_panel(ctx, None))
            return

        # A próxima faixa pode já ter sido resolvida pelo pré-carregamento.
        state.current = state.queue.pop(0)

        self._schedule_preload(state)

        if state.current.get("_needs_fetch"):
            self.bot.loop.create_task(self._fetch_and_play(ctx, state.current))
        else:
            self._start_playing(ctx, state.current)  # _start_playing já chama _update_control_panel

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(120)
        vc = ctx.voice_client
        if vc and not vc.is_playing():
            await vc.disconnect()
            await ctx.send(
                embed=music_embed("Desconectado", "Saí por inatividade (2 min).", discord.Color.greyple())
            )

    async def _update_control_panel(self, ctx: commands.Context, song: dict | None):
        """Envia ou edita o painel de controle fixo com botões interativos."""
        state = self._state(ctx.guild.id)
        if song is None:
            if state.control_message:
                try:
                    await state.control_message.edit(view=None)
                except Exception:
                    pass
                state.control_message = None
            return

        url = song.get("url", "")
        embed = discord.Embed(
            title="Tocando agora",
            description=f"[{song['title']}]({url})" if url else song["title"],
            color=discord.Color.green(),
        )
        # Barra de progresso
        elapsed = time.monotonic() - state._started_at if state._started_at else 0
        embed.add_field(
            name="Progresso",
            value=self._progress_bar(elapsed, song.get("duration", 0)),
            inline=False,
        )
        embed.add_field(name="Canal", value=song.get("uploader", "?"))
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        loop_status = "🔁 Song" if state.loop else ("🔁 Queue" if state.loop_queue else "Off")
        embed.add_field(name="Loop", value=loop_status)
        if state.queue:
            embed.add_field(name="A seguir", value=state.queue[0]["title"][:50], inline=False)
        if song.get("thumbnail"):
            embed.set_thumbnail(url=song["thumbnail"])
        embed.set_footer(text="⏸ pausar  ⏭ pular  🔀 shuffle  🔁 loop (song→queue→off)  ⏹ parar")

        view = MusicControlView(self, ctx.guild.id)

        if state.control_message:
            try:
                await state.control_message.edit(embed=embed, view=view)
                return
            except Exception:
                state.control_message = None

        channel = state.control_ctx.channel if state.control_ctx else ctx.channel
        state.control_message = await channel.send(embed=embed, view=view)
        state.control_ctx = ctx

    async def _ensure_voice(self, ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            await ctx.send(embed=music_embed("Erro", "Entre em um canal de voz primeiro.", discord.Color.red()))
            return False
        canal = ctx.author.voice.channel
        if ctx.voice_client and ctx.voice_client.channel == canal:
            return True

        # A conexão de voz do Discord às vezes cai por soluço de rede
        # (ex.: ClientOSError / WinError 64). Tentamos algumas vezes antes de desistir.
        last_exc = None
        for tentativa in range(3):
            try:
                if ctx.voice_client:
                    await ctx.voice_client.move_to(canal)
                else:
                    await canal.connect()
                return True
            except Exception as e:
                last_exc = e
                log.warning("Falha ao conectar na voz (tentativa %d/3): %s", tentativa + 1, e)
                # Limpa uma conexão pela metade antes de tentar de novo.
                if ctx.voice_client:
                    try:
                        await ctx.voice_client.disconnect(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(1.5)

        log.error("Não foi possível conectar ao canal de voz: %s", last_exc)
        await ctx.send(embed=music_embed(
            "Erro de conexão",
            "Não consegui entrar no canal de voz — a conexão com o Discord oscilou. "
            "Tenta de novo daqui a pouco. 🎧",
            discord.Color.red(),
        ))
        return False

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
            # _play_next → _start_playing → _update_control_panel cuida do embed
            self._play_next(ctx)
        else:
            self._schedule_preload(state)
            url = song.get("url", "")
            embed = discord.Embed(
                title="Adicionado à fila",
                description=f"[{song['title']}]({url})" if url else song["title"],
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Posição", value=str(len(state.queue)))
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

    @commands.hybrid_command(name="join", aliases=["entrar"], help="Entra no seu canal de voz.")
    @commands.guild_only()
    async def join(self, ctx: commands.Context):
        if await self._ensure_voice(ctx):
            await ctx.send(embed=music_embed("Conectado", f"Entrei em **{ctx.author.voice.channel.name}**."))

    @commands.hybrid_command(name="m", aliases=["tocar"], help="Toca música por nome, ou link do YouTube, Spotify ou SoundCloud (faixa/playlist).")
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.guild_only()
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
                try:
                    songs = await self._extract_spotify(query)
                except Exception as e:
                    log.error("Erro ao carregar do Spotify: %s", e)
                    await msg.delete()
                    return await ctx.send(embed=music_embed(
                        "Erro no Spotify",
                        "Não consegui carregar esse link do Spotify 😕\n"
                        "Confere se o link tá certo e tenta de novo.",
                        discord.Color.red(),
                    ))
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

        # ── Playlist do YouTube ou set do SoundCloud ──────────────────────
        if self._is_yt_playlist(query) or self._is_soundcloud_set(query):
            is_sc = self._is_soundcloud_set(query)
            origem = "SoundCloud" if is_sc else "YouTube"
            cor = discord.Color.orange() if is_sc else discord.Color.red()
            msg = await ctx.send(embed=music_embed(f"{origem} Playlist 🎵", "Carregando playlist...", cor))
            async with ctx.typing():
                songs = await self._extract_playlist(query)
            await msg.delete()

            if not songs:
                return await ctx.send(embed=music_embed("Erro", "Não consegui carregar essa playlist.", discord.Color.red()))
            await self._enqueue_many(ctx, songs, f"{origem} Playlist")
            return

        # ── Música/URL única ──────────────────────────────────────────────
        async with ctx.typing():
            song = await self._search(query)
        if song is None:
            return await ctx.send(embed=music_embed("Erro", "Não consegui encontrar essa música.", discord.Color.red()))
        await self._enqueue_one(ctx, song)

    @commands.hybrid_command(name="pause", aliases=["pausar"], help="Pausa a música atual.")
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send(embed=music_embed("Pausado", "Música pausada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está tocando.", discord.Color.orange()))

    @commands.hybrid_command(name="resume", aliases=["continuar"], help="Retoma a música pausada.")
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send(embed=music_embed("Retomado", "Música retomada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está pausado.", discord.Color.orange()))

    @commands.hybrid_command(name="skip", aliases=["s", "pular"], help="Pula para a próxima música.")
    @commands.cooldown(1, 2, commands.BucketType.user)
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
            await ctx.send(embed=music_embed("Pulado", "Música pulada."))
        else:
            await ctx.send(embed=music_embed("Erro", "Nada está tocando.", discord.Color.orange()))

    @commands.hybrid_command(name="stop", aliases=["parar"], help="Para a música e limpa a fila.")
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        state._preloaded = None
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        await ctx.send(embed=music_embed("Parado", "Fila limpa e bot desconectado.", discord.Color.red()))

    @commands.hybrid_command(name="volume", aliases=["vol"], help="Ajusta o volume (0–100).")
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, vol: int):
        if not 0 <= vol <= 100:
            return await ctx.send(embed=music_embed("Erro", "O volume deve ser entre 0 e 100.", discord.Color.orange()))
        state = self._state(ctx.guild.id)
        state.volume = vol / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = state.volume
        await ctx.send(embed=music_embed("Volume", f"Volume ajustado para **{vol}%**."))

    @commands.hybrid_command(name="nowplaying", aliases=["np", "tocando"], help="Mostra a música atual com barra de progresso.")
    @commands.guild_only()
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
        elapsed = time.monotonic() - state._started_at if state._started_at else 0
        embed.add_field(
            name="Progresso",
            value=self._progress_bar(elapsed, song.get("duration", 0)),
            inline=False,
        )
        embed.add_field(name="Canal", value=song.get("uploader", "?"))
        loop_status = "🔁 Song" if state.loop else ("🔁 Queue" if state.loop_queue else "Off")
        embed.add_field(name="Loop", value=loop_status)
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        if song.get("thumbnail"):
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="queue", aliases=["fila", "q"], help="Exibe a fila de músicas.")
    @commands.guild_only()
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
        loop_label = "Song" if state.loop else ("Queue" if state.loop_queue else "Off")
        embed.set_footer(text=f"Total na fila: {len(state.queue)} | Loop: {loop_label}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="loop", help="Cicla o loop: sem loop → loop da música → loop da fila.")
    @commands.guild_only()
    async def loop_cmd(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        if not state.loop and not state.loop_queue:
            state.loop = True
            msg = "🔁 Loop da **música atual** ativado."
        elif state.loop:
            state.loop = False
            state.loop_queue = True
            msg = "🔁 Loop da **fila inteira** ativado."
        else:
            state.loop = False
            state.loop_queue = False
            msg = "Loop **desativado**."
        await ctx.send(embed=music_embed("Loop", msg))

    @commands.hybrid_command(name="clear", aliases=["limpar"], help="Limpa a fila sem parar a música.")
    @commands.guild_only()
    async def clear_queue(self, ctx: commands.Context):
        state = self._state(ctx.guild.id)
        state.queue.clear()
        state._preloaded = None
        await ctx.send(embed=music_embed("Fila limpa", "Todas as músicas da fila foram removidas."))

    @commands.hybrid_command(name="remove", aliases=["remover"], help="Remove uma música da fila pelo número.")
    @commands.guild_only()
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
        else:
            # Deixa o handler global tratar (mensagem amigável + log).
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
