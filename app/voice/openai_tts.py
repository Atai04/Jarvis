"""Bounded Speech API generation followed by local macOS playback."""

import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import APITimeoutError, AsyncOpenAI

from app.config.settings import Settings
from app.voice.diagnostics import PlaybackAttempt, speech_attempt
from app.voice.privacy import private_audio_request
from app.voice.tts import (
    SpeechError,
    SpeechProvider,
    _finish_cleanup,
    _reap,
    _spawn_playback,
    validate_speech,
)


class SpeechGenerationError(SpeechError):
    """No local playback has started; local fallback is still safe."""


class OpenAISpeechSynthesizer:
    def __init__(self, settings: Settings, fallback: SpeechProvider | None = None):
        self.settings = settings
        self.fallback = fallback
        self._speaking = False

    async def speak(self, text: str) -> None:
        with speech_attempt("openai") as attempt:
            await self._speak(text, attempt)

    async def _speak(self, text: str, attempt: PlaybackAttempt) -> None:
        settings = self.settings
        validate_speech(settings, text)
        if settings.voice_tts_provider != "openai":
            raise SpeechError("OpenAI speech requires explicit provider selection.")
        if len(text) > 4096:
            raise SpeechError("OpenAI speech accepts at most 4096 input characters.")
        if not settings.openai_api_key.strip():
            raise SpeechError("Set OPENAI_API_KEY before using OpenAI speech.")
        if not shutil.which("/usr/bin/afplay"):
            raise SpeechError("macOS /usr/bin/afplay is unavailable.")
        if self._speaking:
            raise SpeechError("Speech is already playing on this synthesizer.")
        self._speaking = True
        try:
            try:
                with TemporaryDirectory(prefix="jarvis-speech-") as directory:
                    path = (
                        Path(directory) / f"speech.{settings.voice_openai_tts_format}"
                    )
                    await self._generate(text, path)
                    # From this point onward failures must never trigger replay.
                    await self._play(path, attempt)
            except SpeechGenerationError:
                if self.fallback is None or not settings.voice_tts_fallback_to_macos:
                    raise
                attempt.fallback_occurred = True
                await self.fallback.speak(text)
        except SpeechError:
            raise
        except Exception:  # noqa: BLE001 - never expose SDK, OS, or audio diagnostics
            raise SpeechError("OpenAI speech failed safely.") from None
        finally:
            self._speaking = False

    async def _generate(self, text: str, path: Path) -> None:
        settings = self.settings
        token = private_audio_request.set(True)
        try:
            parameters = {
                "model": settings.voice_openai_tts_model,
                "voice": settings.voice_openai_tts_voice,
                "input": text,
                "response_format": settings.voice_openai_tts_format,
            }
            if settings.voice_openai_tts_instructions:
                parameters["instructions"] = settings.voice_openai_tts_instructions
            async with asyncio.timeout(
                settings.voice_openai_tts_request_timeout_seconds
            ):
                async with AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    base_url="https://api.openai.com/v1",
                    max_retries=0,
                    timeout=settings.voice_openai_tts_request_timeout_seconds,
                ) as client:
                    async with client.audio.speech.with_streaming_response.create(
                        **parameters
                    ) as response:
                        total = 0
                        with path.open("xb") as audio:
                            async for chunk in response.iter_bytes(chunk_size=65536):
                                total += len(chunk)
                                if total > settings.voice_openai_tts_max_audio_bytes:
                                    raise SpeechGenerationError(
                                        "Generated audio exceeds the size limit."
                                    )
                                audio.write(chunk)
                        if not total:
                            raise SpeechGenerationError("OpenAI returned empty audio.")
        except TimeoutError, APITimeoutError:
            raise SpeechGenerationError(
                "Speech generation timed out; no retry was made."
            ) from None
        except SpeechGenerationError:
            raise
        except Exception:  # noqa: BLE001 - API error bodies may contain private text
            raise SpeechGenerationError(
                "Speech generation failed. Check API access, quota, and connectivity."
            ) from None
        finally:
            private_audio_request.reset(token)

    async def _play(self, path: Path, attempt: PlaybackAttempt) -> None:
        spawn = None
        try:
            async with asyncio.timeout(self.settings.voice_tts_timeout_seconds):
                spawn = asyncio.create_task(
                    _spawn_playback(
                        attempt,
                        "openai",
                        "/usr/bin/afplay",
                        str(path),
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                )
                process = await asyncio.shield(spawn)
                await process.wait()
                if process.returncode != 0:
                    raise SpeechError(
                        "Generated speech could not be played. Check audio output."
                    )
        except TimeoutError:
            raise SpeechError("Speech playback timed out and was stopped.") from None
        except OSError:
            raise SpeechError("Could not play generated speech.") from None
        finally:
            if spawn is not None:
                try:
                    await _finish_cleanup(asyncio.create_task(_reap(spawn)))
                except Exception:  # noqa: BLE001 - no native diagnostics in CLI
                    raise SpeechError(
                        "Could not stop audio playback; check the audio process."
                    ) from None
