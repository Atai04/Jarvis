"""Local macOS speech, with stdin-only text and owned subprocess cleanup."""

import asyncio
import sys
from typing import Protocol

from app.config.settings import Settings
from app.voice.diagnostics import PlaybackAttempt, speech_attempt


class SpeechError(RuntimeError):
    """Public error that never includes spoken text or subprocess diagnostics."""


class SpeechProvider(Protocol):
    async def speak(self, text: str) -> None: ...


async def _finish_cleanup(task: asyncio.Task) -> None:
    """Finish resource cleanup even if the caller cancels repeatedly."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _spawn_playback(attempt: PlaybackAttempt, provider: str, *args, **kwargs):
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    # Set this inside the shielded creation task, including cancellation races.
    attempt.playback_provider = provider
    return process


async def _reap(spawn: asyncio.Task) -> None:
    try:
        process = await spawn
    except OSError, ValueError:
        return  # Creation failed; there is no child to release.
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await asyncio.wait_for(process.wait(), timeout=1)
    else:
        await process.wait()


def validate_speech(settings: Settings, text: str) -> None:
    if not settings.voice_tts_enabled:
        raise SpeechError("Speech is disabled. Set VOICE_TTS_ENABLED=true to opt in.")
    if sys.platform != "darwin":
        raise SpeechError("Native speech requires macOS.")
    if not isinstance(text, str) or not text.strip():
        raise SpeechError("Enter nonempty text to speak.")
    if len(text) > settings.voice_tts_max_text_length:
        raise SpeechError("Text exceeds the configured speech length limit.")
    if (
        "[[" in text
        or "]]" in text
        or any(not char.isprintable() and char not in "\n\t" for char in text)
    ):
        raise SpeechError(
            "Speech requires plain text without speech markup or control characters."
        )


class SpeechSynthesizer:
    """One playback at a time per instance; cancel the speak task to stop it.

    Awaiting cancellation waits for terminate/kill and process reaping. No shell,
    audio files, cloud service, or application logging is involved.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._speaking = False

    async def speak(self, text: str) -> None:
        with speech_attempt("macos") as attempt:
            await self._speak(text, attempt)

    async def _speak(self, text: str, attempt: PlaybackAttempt) -> None:
        settings = self.settings
        validate_speech(settings, text)
        if self._speaking:
            raise SpeechError("Speech is already playing on this synthesizer.")
        self._speaking = True
        arguments = ["/usr/bin/say", "-r", str(settings.voice_tts_rate)]
        if settings.voice_tts_voice is not None:
            arguments.extend(["-v", settings.voice_tts_voice])
        arguments.extend(["-f", "-"])
        spawn = None
        try:
            async with asyncio.timeout(settings.voice_tts_timeout_seconds):
                # Shield creation so cancellation cannot lose ownership of a new child.
                spawn = asyncio.create_task(
                    _spawn_playback(
                        attempt,
                        "macos",
                        *arguments,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                )
                process = await asyncio.shield(spawn)
                await process.communicate(text.encode("utf-8"))
                if process.returncode != 0:
                    raise SpeechError(
                        "Speech failed. Check the installed voice and audio output."
                    )
        except FileNotFoundError:
            raise SpeechError("macOS /usr/bin/say is unavailable.") from None
        except TimeoutError:
            raise SpeechError("Speech timed out and was stopped.") from None
        except OSError, ValueError:
            raise SpeechError("Could not start or play native speech.") from None
        except SpeechError:
            raise
        except Exception:  # noqa: BLE001 - subprocess details must not disclose content
            raise SpeechError("Native speech failed safely.") from None
        finally:
            try:
                if spawn is not None:
                    try:
                        await _finish_cleanup(asyncio.create_task(_reap(spawn)))
                    except Exception:  # noqa: BLE001 - sanitize cleanup diagnostics too
                        raise SpeechError(
                            "Could not stop native speech; check the audio process."
                        ) from None
            finally:
                self._speaking = False
