"""Tests for the Voice module (TTS/STT)."""

from __future__ import annotations

import pytest

from aion_core.voice import Voice, VoiceConfig, get_voice


class TestVoiceBackendDetection:
    """Verify Voice detects available backends gracefully."""

    def test_voice_instantiable_without_deps(self, tmp_path):
        # Even on a system with no TTS/STT installed, Voice should construct
        cfg = VoiceConfig(output_dir=tmp_path)
        v = Voice(cfg)
        assert v is not None
        assert v.tts_backend in ("pyttsx3", "say", "espeak", "espeak-ng", "none")
        assert v.stt_backend in ("whisper", "none")

    def test_voice_singleton(self):
        v1 = get_voice()
        v2 = get_voice()
        assert v1 is v2


class TestVoiceSpeakFallback:
    """The 'none' backend should print, not crash."""

    @pytest.mark.asyncio
    async def test_speak_with_none_backend_prints(self, tmp_path, capsys):
        cfg = VoiceConfig(output_dir=tmp_path, tts_backend="none")
        v = Voice(cfg)
        result = await v.speak("Hello world")
        # 'none' backend returns None and prints
        assert result is None
        out = capsys.readouterr().out
        assert "Hello world" in out

    @pytest.mark.asyncio
    async def test_speak_empty_text_returns_none(self, tmp_path):
        cfg = VoiceConfig(output_dir=tmp_path)
        v = Voice(cfg)
        result = await v.speak("")
        assert result is None

    @pytest.mark.asyncio
    async def test_speak_to_file(self, tmp_path):
        # Even with 'none' backend, calling speak with output_file should return None
        cfg = VoiceConfig(output_dir=tmp_path, tts_backend="none")
        v = Voice(cfg)
        out_path = tmp_path / "out.wav"
        result = await v.speak("Hello", output_file=out_path)
        # None backend returns None
        assert result is None


class TestVoiceSTTFallback:
    """STT should fail gracefully when no backend available."""

    @pytest.mark.asyncio
    async def test_transcribe_nonexistent_file_raises(self, tmp_path):
        cfg = VoiceConfig(output_dir=tmp_path, stt_backend="none")
        v = Voice(cfg)
        with pytest.raises(FileNotFoundError):
            await v.transcribe(tmp_path / "nope.wav")

    @pytest.mark.asyncio
    async def test_transcribe_none_backend_returns_empty(self, tmp_path):
        cfg = VoiceConfig(output_dir=tmp_path, stt_backend="none")
        v = Voice(cfg)
        # Create a tiny fake audio file
        audio = tmp_path / "fake.wav"
        audio.write_bytes(b"fake audio bytes")
        result = await v.transcribe(audio)
        assert result == ""


class TestVoiceListVoices:
    """list_voices should not crash on any backend."""

    def test_list_voices_returns_list(self, tmp_path):
        cfg = VoiceConfig(output_dir=tmp_path)
        v = Voice(cfg)
        voices = v.list_voices()
        assert isinstance(voices, list)
