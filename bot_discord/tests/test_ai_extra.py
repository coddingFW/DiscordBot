"""Testes adicionais de lógica pura do cog de IA."""
import pytest
from cogs.ai import (
    _norm_channel,
    _build_system_prompt,
    TONE_PRESETS,
    VOICE_PRESETS,
    DEFAULT_TONE,
    DEFAULT_VOICE,
    _friendly_error,
    AI,
)


# ── _norm_channel ─────────────────────────────────────────────────────────────

def test_norm_channel_minusculas():
    assert _norm_channel("GERAL") == "geral"


def test_norm_channel_remove_acento():
    assert _norm_channel("Músicas") == "musicas"


def test_norm_channel_espacos_viram_hifen():
    assert _norm_channel("material academico") == "material-academico"


def test_norm_channel_acento_complexo():
    assert _norm_channel("Material Acadêmico") == "material-academico"


def test_norm_channel_strip():
    assert _norm_channel("  geral  ") == "geral"


# ── _build_system_prompt ──────────────────────────────────────────────────────

def test_build_system_prompt_contem_tom():
    for tom in TONE_PRESETS:
        prompt = _build_system_prompt(tom)
        _, instrucao = TONE_PRESETS[tom]
        assert instrucao in prompt


def test_build_system_prompt_tom_invalido_usa_padrao():
    prompt = _build_system_prompt("tom_que_nao_existe")
    _, instrucao_padrao = TONE_PRESETS[DEFAULT_TONE]
    assert instrucao_padrao in prompt


def test_build_system_prompt_contem_criador():
    prompt = _build_system_prompt(DEFAULT_TONE)
    assert "coddingFW" in prompt


# ── TONE_PRESETS ──────────────────────────────────────────────────────────────

def test_tone_presets_tem_5_opcoes():
    assert len(TONE_PRESETS) == 5


def test_tone_presets_todos_tem_rotulo_e_instrucao():
    for chave, (rotulo, instrucao) in TONE_PRESETS.items():
        assert rotulo, f"Tom '{chave}' sem rótulo"
        assert instrucao, f"Tom '{chave}' sem instrução"


def test_default_tone_existe_nos_presets():
    assert DEFAULT_TONE in TONE_PRESETS


# ── VOICE_PRESETS ─────────────────────────────────────────────────────────────

def test_voice_presets_tem_7_vozes():
    assert len(VOICE_PRESETS) == 7


def test_voice_presets_todos_tem_rotulo_e_id():
    for chave, (rotulo, voice_id) in VOICE_PRESETS.items():
        assert rotulo, f"Voz '{chave}' sem rótulo"
        assert "pt-BR" in voice_id, f"Voz '{chave}' não é pt-BR"


def test_default_voice_existe_nos_presets():
    assert DEFAULT_VOICE in VOICE_PRESETS


# ── _friendly_error ───────────────────────────────────────────────────────────

def test_friendly_timeout():
    msg = _friendly_error(Exception("connection timeout"))
    assert "conexão" in msg.lower() or "rede" in msg.lower() or "servidor" in msg.lower()


def test_friendly_500():
    msg = _friendly_error(Exception("500 internal server error"))
    assert "interno" in msg.lower()


def test_friendly_rate_limit_minuto():
    msg = _friendly_error(Exception("429 too many requests"))
    assert "rápido" in msg.lower() or "devagar" in msg.lower() or "espera" in msg.lower()


# ── AI._check_rate ────────────────────────────────────────────────────────────

def test_check_rate_permite_dentro_do_limite():
    cog = AI.__new__(AI)
    cog._rate = {}
    for _ in range(5):
        assert cog._check_rate(1) is True


def test_check_rate_bloqueia_apos_limite():
    cog = AI.__new__(AI)
    cog._rate = {}
    for _ in range(5):
        cog._check_rate(2)
    assert cog._check_rate(2) is False


def test_check_rate_usuarios_independentes():
    cog = AI.__new__(AI)
    cog._rate = {}
    for _ in range(5):
        cog._check_rate(10)
    # usuário diferente não deve ser afetado
    assert cog._check_rate(20) is True


# ── AI._is_ai_channel ─────────────────────────────────────────────────────────

def test_is_ai_channel_nome_padrao():
    cog = AI.__new__(AI)
    cog._guild_channels = {}

    channel = type("Ch", (), {"name": "ia", "guild": type("G", (), {"id": 1})()})()
    assert cog._is_ai_channel(channel) is True


def test_is_ai_channel_nome_errado():
    cog = AI.__new__(AI)
    cog._guild_channels = {}

    channel = type("Ch", (), {"name": "geral", "guild": type("G", (), {"id": 1})()})()
    assert cog._is_ai_channel(channel) is False


def test_is_ai_channel_configurado_por_servidor():
    cog = AI.__new__(AI)
    cog._guild_channels = {1: 999}

    channel = type("Ch", (), {"id": 999, "name": "outro", "guild": type("G", (), {"id": 1})()})()
    assert cog._is_ai_channel(channel) is True


def test_is_ai_channel_configurado_id_errado():
    cog = AI.__new__(AI)
    cog._guild_channels = {1: 999}

    channel = type("Ch", (), {"id": 888, "name": "ia", "guild": type("G", (), {"id": 1})()})()
    assert cog._is_ai_channel(channel) is False


# ── AI._tone_for / _voice_id_for ──────────────────────────────────────────────

def test_tone_for_retorna_padrao_sem_config():
    cog = AI.__new__(AI)
    cog._guild_tones = {}
    assert cog._tone_for(1) == DEFAULT_TONE


def test_tone_for_retorna_configurado():
    cog = AI.__new__(AI)
    cog._guild_tones = {1: "formal"}
    assert cog._tone_for(1) == "formal"


def test_tone_for_none_retorna_padrao():
    cog = AI.__new__(AI)
    cog._guild_tones = {}
    assert cog._tone_for(None) == DEFAULT_TONE


def test_voice_id_for_retorna_padrao():
    cog = AI.__new__(AI)
    cog._guild_voices = {}
    voice_id = cog._voice_id_for(1)
    _, expected = VOICE_PRESETS[DEFAULT_VOICE]
    assert voice_id == expected


def test_voice_id_for_retorna_configurado():
    cog = AI.__new__(AI)
    cog._guild_voices = {1: "antonio"}
    voice_id = cog._voice_id_for(1)
    _, expected = VOICE_PRESETS["antonio"]
    assert voice_id == expected
