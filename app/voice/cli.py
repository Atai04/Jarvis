"""Explicit recording and opt-in transcription commands."""

import argparse
import asyncio

from app.config.settings import Settings, get_settings
from app.voice import MicrophoneRecorder, RecordingError
from app.voice.providers import build_speech_provider
from app.voice.transcription import AudioTranscriber, TranscriptionError
from app.voice.tts import SpeechError


def record_command(settings: Settings) -> None:
    if not settings.voice_recording_enabled:
        print("Recording disabled. Set VOICE_RECORDING_ENABLED=true to opt in.")
        return
    try:
        with MicrophoneRecorder(
            settings.voice_sample_rate, settings.voice_max_duration_seconds
        ) as recorder:
            recorder.start()
            input(
                f"Recording locally (maximum {settings.voice_max_duration_seconds:g}s). "
                "Press Enter to stop; Ctrl-C cancels. "
            )
            recorder.stop()
            print("Local WAV created; temporary recording will now be deleted.")
    except KeyboardInterrupt, EOFError:
        print("\nRecording cancelled; temporary audio deleted.")
    except RecordingError as exc:
        print(f"Recording failed: {exc}")


async def transcribe_command(settings: Settings) -> None:
    if not (settings.voice_recording_enabled and settings.voice_transcription_enabled):
        print(
            "Enable VOICE_RECORDING_ENABLED and VOICE_TRANSCRIPTION_ENABLED to transcribe."
        )
        return
    if not settings.openai_api_key.strip():
        print("Set OPENAI_API_KEY before transcribing.")
        return
    try:
        with MicrophoneRecorder(
            settings.voice_sample_rate, settings.voice_max_duration_seconds
        ) as recorder:
            print("This recording will be uploaded to OpenAI for paid transcription.")
            recorder.start()
            input(
                f"Recording (maximum {settings.voice_max_duration_seconds:g}s). "
                "Enter stops and uploads; Ctrl-C cancels: "
            )
            recorder.stop()
            text = await AudioTranscriber(settings).transcribe(recorder)
            # Treat recognized text as untrusted display content, never a command.
            safe_text = "".join(
                char for char in text if char.isprintable() or char == "\n"
            )
            print(f"Recognized text (not executed):\n{safe_text}")
    except KeyboardInterrupt, EOFError:
        print("\nTranscription cancelled; temporary audio deleted.")
    except (RecordingError, TranscriptionError) as exc:
        print(f"Voice failed: {exc}")


async def speak_command(settings: Settings) -> None:
    if not settings.voice_tts_enabled:
        print("Speech disabled. Set VOICE_TTS_ENABLED=true to opt in.")
        return
    try:
        if settings.voice_tts_provider == "openai":
            print("OpenAI speech sends text to a paid API. Playback is AI-generated.")
            if settings.voice_tts_fallback_to_macos:
                print("Local macOS fallback is enabled for generation failures only.")
            text = input("Text to send to OpenAI (Ctrl-C cancels): ")
            print("Generating speech; Ctrl-C cancels.")
        else:
            text = input("Text to speak locally (Ctrl-C cancels): ")
            print("Speaking locally; Ctrl-C stops playback.")
        await build_speech_provider(settings).speak(text)
        print("Speech finished.")
    except KeyboardInterrupt, EOFError:
        print("\nSpeech cancelled.")
    except asyncio.CancelledError:
        print("\nSpeech stopped.")
        raise
    except SpeechError as exc:
        print(f"Speech failed: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument(
        "--transcribe", action="store_true", help="Record and upload to OpenAI"
    )
    commands.add_argument(
        "--speak", action="store_true", help="Speak using the configured TTS provider"
    )
    args = parser.parse_args()
    try:
        if args.speak:
            asyncio.run(speak_command(get_settings()))
        elif args.transcribe:
            asyncio.run(transcribe_command(get_settings()))
        else:
            record_command(get_settings())
    except KeyboardInterrupt:
        print("\nVoice command stopped.")
