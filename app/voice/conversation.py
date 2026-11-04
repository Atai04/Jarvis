"""One explicitly activated voice turn through the existing agent and permissions."""

import asyncio
import os
import sys
import termios
from contextlib import ExitStack

from app.agent.orchestrator import AgentOrchestrator
from app.config.settings import Settings
from app.utils.terminal_input import suppress_terminal_input
from app.voice import MicrophoneRecorder
from app.voice.privacy import private_audio_request
from app.voice.providers import build_speech_provider, validate_speech_configuration
from app.voice.transcription import AudioTranscriber


def _terminal_fd() -> int:
    if not sys.stdin.isatty():
        raise ValueError("Voice mode requires an interactive terminal.")
    return sys.stdin.fileno()


async def _wait_for_enter(fd: int, duration: float) -> None:
    """No worker thread or pending input() may survive into tool confirmation."""
    loop = asyncio.get_running_loop()
    entered = loop.create_future()

    def readable():
        if entered.done():
            return
        try:
            char = os.read(fd, 1)
            if not char:
                entered.set_exception(EOFError())
            elif char == b"\n":
                entered.set_result(None)
        except OSError:
            entered.set_exception(EOFError())

    try:
        loop.add_reader(fd, readable)
        try:
            async with asyncio.timeout(duration):
                await entered
        except TimeoutError:
            pass  # Proceed automatically at the recording limit.
    finally:
        loop.remove_reader(fd)
        if not entered.done():
            entered.cancel()
        # Discard pretyped input: it must never approve a later tool confirmation.
        if os.isatty(fd):
            termios.tcflush(fd, termios.TCIFLUSH)


def _display(text: str) -> str:
    return "".join(char for char in text if char.isprintable() or char == "\n")


class VoiceConversation:
    def __init__(self, settings: Settings, agent: AgentOrchestrator):
        self.settings = settings
        self.agent = agent
        self._active = False

    async def run(self) -> None:
        if self._active:
            print("Voice interaction already active.")
            return
        settings = self.settings
        if not (
            settings.voice_recording_enabled
            and settings.voice_transcription_enabled
            and settings.voice_tts_enabled
        ):
            print("Enable voice recording, transcription and TTS before using /voice.")
            return
        if not settings.openai_api_key.strip():
            print("Set OPENAI_API_KEY before using /voice.")
            return
        self._active = True
        token = private_audio_request.set(True)
        input_scope = ExitStack()
        stage = "Configuration"
        try:
            validate_speech_configuration(settings)
            fd = _terminal_fd()
            speaker = build_speech_provider(settings)
            print(
                "Voice mode uploads audio for transcription, processes it with JARVIS, "
                "and speaks the response. API charges apply; tool confirmations remain typed."
            )
            print(
                f"Speech provider: {settings.voice_tts_provider} (AI-generated speech)."
            )
            stage = "Recording"
            with MicrophoneRecorder(
                settings.voice_sample_rate, settings.voice_max_duration_seconds
            ) as recorder:
                recorder.start()
                print(
                    f"Recording — Enter stops; maximum {settings.voice_max_duration_seconds:g}s. "
                    "Ctrl-C cancels."
                )
                await _wait_for_enter(fd, settings.voice_max_duration_seconds)
                input_scope.enter_context(suppress_terminal_input(fd))
                recorder.stop()
                stage = "Transcribing"
                print(
                    "Transcribing… Keyboard input is ignored except at permission prompts; Ctrl-C cancels."
                )
                transcript = await AudioTranscriber(settings).transcribe(recorder)
            if not isinstance(transcript, str) or not transcript.strip():
                print("No speech recognized; voice interaction stopped.")
                return
            print(f"You (voice) > {_display(transcript)}")
            stage = "Processing"
            print("Processing…")
            # This is user input, not a shell command, system prompt or CLI command.
            response = await self.agent.run(transcript)
            if not isinstance(response, str) or not response.strip():
                print("No response to speak; voice interaction stopped.")
                return
            print(f"JARVIS > {_display(response)}")
            stage = "Speaking"
            print("Speaking…")
            await speaker.speak(response)
            print("Completed — idle. Type /voice for another interaction.")
        except KeyboardInterrupt, EOFError:
            print("Voice interaction cancelled.")
        except asyncio.CancelledError:
            print("Voice interaction cancelled.")
            raise
        except Exception:  # noqa: BLE001 - do not expose transcripts in backend errors
            if stage == "Speaking":
                print(
                    "Speech failed; the text response remains above. Voice mode is idle."
                )
            else:
                print(
                    f"Voice {stage.lower()} failed; interaction stopped. Check configuration and access."
                )
        finally:
            try:
                input_scope.close()
            finally:
                private_audio_request.reset(token)
                self._active = False
