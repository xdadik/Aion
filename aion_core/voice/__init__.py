"""Aion Hand Voice Module — TTS + STT with graceful fallback.

Provides text-to-speech and speech-to-text capabilities using whatever
backend is available on the host system. Designed to work with ZERO
optional dependencies — falls back to system tools (espeak, say) and
skips STT entirely if no engine is installed.

Backends tried, in order:
    TTS:
        1. pyttsx3 (cross-platform, offline)
        2. macOS `say` (built-in on mac)
        3. Linux `espeak` / `espeak-ng`
        4. Print to stdout (silent fallback)

    STT:
        1. whisper (openai-whisper package)
        2. macOS `say` does NOT do STT; use `sox` + whisper
        3. Skip with warning if nothing available

Usage:
    from aion_core.voice import Voice
    v = Voice()
    await v.speak("Hello world")
    text = await v.transcribe("/path/to/audio.wav")
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger("aion_hand.voice")


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _has(cmd: str) -> bool:
    """True if a CLI command exists on PATH."""
    return shutil.which(cmd) is not None


def _detect_tts_backend() -> str:
    """Return 'pyttsx3', 'say', 'espeak', or 'none'."""
    try:
        import pyttsx3  # type: ignore[import-not-found]  # noqa: F401

        return "pyttsx3"
    except ImportError:
        pass
    if sys.platform == "darwin" and _has("say"):
        return "say"
    if _has("espeak-ng"):
        return "espeak-ng"
    if _has("espeak"):
        return "espeak"
    return "none"


def _detect_stt_backend() -> str:
    """Return 'whisper' or 'none'."""
    try:
        import whisper  # type: ignore[import-not-found]  # noqa: F401

        return "whisper"
    except ImportError:
        pass
    return "none"


# ---------------------------------------------------------------------------
# Voice config
# ---------------------------------------------------------------------------


@dataclass
class VoiceConfig:
    """Voice configuration."""

    tts_backend: str = ""  # auto-detect if empty
    stt_backend: str = ""  # auto-detect if empty
    rate: int = 175  # words per minute (espeak/pyttsx3)
    volume: float = 1.0  # 0.0 - 1.0
    voice_id: str | None = None  # backend-specific voice ID
    output_dir: Path = Path.home() / ".aion-hand" / "voice"


# ---------------------------------------------------------------------------
# Voice main class
# ---------------------------------------------------------------------------


class Voice:
    """Text-to-speech + speech-to-text with multi-backend support."""

    def __init__(self, config: VoiceConfig | None = None) -> None:
        self.config = config or VoiceConfig()
        self._tts = self.config.tts_backend or _detect_tts_backend()
        self._stt = self.config.stt_backend or _detect_stt_backend()
        self._pyttsx3_engine: Any = None
        self._whisper_model: Any = None
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Voice init: tts={self._tts}, stt={self._stt}")

    @property
    def tts_backend(self) -> str:
        return self._tts

    @property
    def stt_backend(self) -> str:
        return self._stt

    # ------------------------------------------------------------------
    #  Text-to-Speech
    # ------------------------------------------------------------------

    async def speak(
        self, text: str, *, output_file: Path | str | None = None
    ) -> Path | None:
        """Speak `text` aloud. If `output_file` is given, save audio there
        instead of playing it. Returns the audio file path if saved, else None.
        """
        if not text.strip():
            return None

        if output_file is not None:
            out_path = Path(output_file)
        else:
            out_path = (
                self.config.output_dir
                / f"tts_{asyncio.get_event_loop().time():.0f}.wav"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self._tts == "pyttsx3":
            return await self._speak_pyttsx3(text, out_path, play=(output_file is None))
        if self._tts == "say":
            return await self._speak_say(text, out_path, play=(output_file is None))
        if self._tts in ("espeak", "espeak-ng"):
            return await self._speak_espeak(text, out_path, play=(output_file is None))

        # Fallback: print to stdout
        print(f"[aion-voice] {text}")
        return None

    async def _speak_pyttsx3(self, text: str, out_path: Path, *, play: bool) -> Path:
        """Use pyttsx3 (cross-platform, offline)."""

        def _run() -> None:
            import pyttsx3  # type: ignore[import-not-found]

            engine = pyttsx3.init()
            engine.setProperty("rate", self.config.rate)
            engine.setProperty("volume", self.config.volume)
            if self.config.voice_id:
                engine.setProperty("voice", self.config.voice_id)
            if play:
                engine.say(text)
                engine.runAndWait()
            else:
                engine.save_to_file(text, str(out_path))
                engine.runAndWait()

        # pyttsx3 is synchronous — run in executor
        await asyncio.get_event_loop().run_in_executor(None, _run)
        return out_path if not play else None

    async def _speak_say(self, text: str, out_path: Path, *, play: bool) -> Path | None:
        """Use macOS `say`."""
        if play:
            cmd = ["say", "-r", str(self.config.rate)]
            if self.config.voice_id:
                cmd += ["-v", self.config.voice_id]
            cmd += [text]
            await asyncio.create_subprocess_exec(*cmd)
            return None
        else:
            cmd = ["say", "-r", str(self.config.rate), "-o", str(out_path)]
            if self.config.voice_id:
                cmd += ["-v", self.config.voice_id]
            cmd += [text]
            await asyncio.create_subprocess_exec(*cmd)
            return out_path

    async def _speak_espeak(
        self, text: str, out_path: Path, *, play: bool
    ) -> Path | None:
        """Use Linux `espeak` / `espeak-ng`."""
        cmd = [
            self._tts,
            "-s",
            str(self.config.rate),
            "-a",
            str(int(self.config.volume * 200)),
        ]
        if self.config.voice_id:
            cmd += ["-v", self.config.voice_id]
        if play:
            cmd += [text]
            await asyncio.create_subprocess_exec(*cmd)
            return None
        else:
            cmd += ["-w", str(out_path), text]
            await asyncio.create_subprocess_exec(*cmd)
            return out_path

    # ------------------------------------------------------------------
    #  Speech-to-Text
    # ------------------------------------------------------------------

    async def transcribe(
        self, audio_path: Path | str, *, language: str | None = None
    ) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path: Path to a .wav / .mp3 / .m4a file.
            language: Optional language code (e.g. 'en', 'es').

        Returns:
            Transcribed text. Empty string if STT unavailable.
        """
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")

        if self._stt == "whisper":
            return await self._transcribe_whisper(path, language)
        logger.warning("No STT backend available. Install: pip install openai-whisper")
        return ""

    async def transcribe_microphone(
        self, duration: float = 5.0, *, language: str | None = None
    ) -> str:
        """Record from the microphone for `duration` seconds and transcribe.

        Falls back to recording via `sox` (Linux/macOS) if available; otherwise
        raises RuntimeError.
        """
        if not _has("sox") and not _has("rec"):
            raise RuntimeError(
                "Microphone recording requires `sox` (rec) to be installed"
            )
        out_path = (
            self.config.output_dir / f"rec_{asyncio.get_event_loop().time():.0f}.wav"
        )
        cmd = ["rec", "-q", str(out_path), "trim", "0", str(duration)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
        return await self.transcribe(out_path, language=language)

    async def _transcribe_whisper(self, path: Path, language: str | None) -> str:
        """Use OpenAI Whisper (local model)."""

        def _run() -> str:
            import whisper  # type: ignore[import-not-found]

            if self._whisper_model is None:
                self._whisper_model = whisper.load_model("base")
            result = self._whisper_model.transcribe(str(path), language=language)
            return str(result.get("text", "")).strip()

        return await asyncio.get_event_loop().run_in_executor(None, _run)

    # ------------------------------------------------------------------
    #  Utility
    # ------------------------------------------------------------------

    def list_voices(self) -> list[str]:
        """Return available voice IDs for the current TTS backend."""
        if self._tts == "say":
            # macOS: `say -v '?'` lists voices
            import subprocess

            try:
                out = subprocess.check_output(["say", "-v", "?"], text=True)
                return [
                    line.split("  ")[0].strip()
                    for line in out.splitlines()
                    if line.strip()
                ]
            except Exception:  # noqa: BLE001
                return []
        if self._tts == "espeak" or self._tts == "espeak-ng":
            import subprocess

            try:
                out = subprocess.check_output([self._tts, "--voices"], text=True)
                lines = out.splitlines()[1:]  # skip header
                return [line.split()[3] for line in lines if len(line.split()) >= 4]
            except Exception:  # noqa: BLE001
                return []
        if self._tts == "pyttsx3":
            try:
                import pyttsx3  # type: ignore[import-not-found]

                eng = pyttsx3.init()
                return [v.id for v in eng.getProperty("voices")]
            except Exception:  # noqa: BLE001
                return []
        return []


# ---------------------------------------------------------------------------
#  Singleton convenience
# ---------------------------------------------------------------------------

_default_voice: Voice | None = None


def get_voice() -> Voice:
    """Return a process-wide Voice singleton."""
    global _default_voice
    if _default_voice is None:
        _default_voice = Voice()
    return _default_voice


__all__ = ["Voice", "VoiceConfig", "get_voice"]
