"""Explicit one-shot local activation followed by the existing voice command."""

import asyncio
import threading

from app.config.settings import Settings
from app.utils.terminal_input import suppress_terminal_input
from app.voice.conversation import VoiceConversation, _terminal_fd
from app.voice.providers import validate_speech_configuration
from app.voice.wake_capture import listen_for_wake
from app.voice.wake_detector import WakeError


async def _listen(phrase: str, timeout: float) -> bool:
    stop = threading.Event()
    ready = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(listen_for_wake, phrase, timeout, stop, ready=ready)
    )
    try:
        while not ready.is_set() and not worker.done():
            await asyncio.sleep(0.02)
        if ready.is_set() and not worker.done():
            print("Listening locally — microphone active. Say Hey Jarvis.")
        return await asyncio.shield(worker)
    finally:
        stop.set()
        # Cancelling to_thread alone leaves native capture running. Await its
        # actual cleanup even after repeated cancellation before restoring stdin.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - preserve cancellation over backend failure
                break
        if not worker.cancelled():
            worker.exception()  # Retrieve failures if cancellation won the race.


class WakeSession:
    def __init__(self, settings: Settings, voice: VoiceConversation):
        self.settings = settings
        self.voice = voice
        self._active = False

    async def run(self) -> None:
        settings = self.settings
        if not settings.voice_wake_enabled:
            print("Wake mode is disabled. Set VOICE_WAKE_ENABLED=true to opt in.")
            return
        if self._active:
            print("Wake session already active.")
            return
        self._active = True
        try:
            if not (
                settings.voice_recording_enabled
                and settings.voice_transcription_enabled
                and settings.voice_tts_enabled
                and settings.openai_api_key.strip()
            ):
                print(
                    "Configure /voice recording, transcription, TTS and API access first."
                )
                return
            validate_speech_configuration(settings)
            fd = _terminal_fd()
            with suppress_terminal_input(fd):
                print(
                    "Preparing local wake listening — microphone capture will be local only. "
                    "Wait for Listening, say Hey Jarvis, then wait for Recording before your command. "
                    "Keyboard input is ignored; Ctrl-C cancels."
                )
                detected = await _listen(
                    settings.voice_wake_phrase, settings.voice_wake_timeout_seconds
                )
            if not detected:
                print("Wake listening timed out — idle.")
                return
            print(
                "Wake phrase detected; wake microphone released. Starting one voice interaction."
            )
            # No audio or recognized text crosses this boundary. Voice creates a
            # fresh recorder, and retains its existing typed permission handling.
            await self.voice.run()
        except asyncio.CancelledError:
            print("Wake session cancelled.")
            raise
        except KeyboardInterrupt, EOFError:
            print("Wake session cancelled.")
        except WakeError as exc:
            print(str(exc))
        except Exception:  # noqa: BLE001 - never expose backend audio or error details
            print(
                "Wake session failed; check local model, microphone permission and voice configuration."
            )
        finally:
            self._active = False
