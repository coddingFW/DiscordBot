"""Testes de lógica pura do cog de música — sem rede nem Discord."""
import pytest

from cogs.music import SearchCache, Music, _find_first


@pytest.fixture
def music():
    # bot=None é suficiente: __init__ não toca em Discord (Spotify fica off sem env).
    return Music(None)


# ── SearchCache ─────────────────────────────────────────────────────────────

def test_cache_set_get():
    cache = SearchCache(ttl=100, maxsize=10)
    cache.set("musica", {"title": "X"})
    assert cache.get("musica") == {"title": "X"}


def test_cache_miss():
    cache = SearchCache(ttl=100, maxsize=10)
    assert cache.get("inexistente") is None


def test_cache_ttl_expira(monkeypatch):
    import cogs.music as m
    fake = {"now": 1000.0}
    monkeypatch.setattr(m.time, "monotonic", lambda: fake["now"])

    cache = SearchCache(ttl=60, maxsize=10)
    cache.set("k", {"v": 1})
    fake["now"] += 61  # passa o TTL
    assert cache.get("k") is None


def test_cache_lru_remove_o_mais_antigo(monkeypatch):
    import cogs.music as m
    fake = {"now": 0.0}
    monkeypatch.setattr(m.time, "monotonic", lambda: fake["now"])

    cache = SearchCache(ttl=10_000, maxsize=2)
    fake["now"] = 1; cache.set("a", {"n": "a"})
    fake["now"] = 2; cache.set("b", {"n": "b"})
    fake["now"] = 3; cache.set("c", {"n": "c"})  # deve expulsar "a"

    assert cache.get("a") is None
    assert cache.get("b") == {"n": "b"}
    assert cache.get("c") == {"n": "c"}


# ── _duration_fmt ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("segundos,esperado", [
    (0, "??:??"),
    (None, "??:??"),
    (65, "01:05"),
    (599, "09:59"),
    (3661, "01:01:01"),
])
def test_duration_fmt(music, segundos, esperado):
    assert music._duration_fmt(segundos) == esperado


# ── Detecção de URL ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://open.spotify.com/track/abc123",
    "https://open.spotify.com/playlist/XyZ789",
    "https://open.spotify.com/album/qwe456",
])
def test_is_spotify_true(music, url):
    assert music._is_spotify(url) is True


@pytest.mark.parametrize("url", [
    "https://youtube.com/watch?v=abc",
    "luan santana música",
    "https://open.spotify.com/artist/abc",  # tipo não suportado
])
def test_is_spotify_false(music, url):
    assert music._is_spotify(url) is False


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc&list=PL123",
    "https://youtube.com/playlist?list=PL999",
    "https://youtu.be/abc?list=PLxyz",
])
def test_is_yt_playlist_true(music, url):
    assert music._is_yt_playlist(url) is True


def test_is_yt_playlist_false(music):
    assert music._is_yt_playlist("https://www.youtube.com/watch?v=abc") is False


# ── _find_first ─────────────────────────────────────────────────────────────

def test_find_first_nested():
    obj = {"a": {"b": [{"c": 1}, {"alvo": 42}]}}
    assert _find_first(obj, "alvo") == 42


def test_find_first_ausente():
    assert _find_first({"a": {"b": 1}}, "x") is None
