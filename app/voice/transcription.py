"""Opt-in transcription of owned recordings; never dispatches recognized text."""

import asyncio
import io
import wave

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.config.settings import Settings
from app.voice.privacy import private_audio_request
from app.voice.recorder import MicrophoneRecorder, RecordingError


class TranscriptionError(RuntimeError):
    """Safe public error without API response bodies or local paths."""


def _validate_wav(data: bytes, max_duration: float) -> None:
    try:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise TranscriptionError("Recording must be a PCM WAV file.")
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise TranscriptionError("Recording is truncated or malformed.")
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or wav.getcomptype() != "NONE"
                or not 8000 <= rate <= 192000
            ):
                raise TranscriptionError("Recording must be mono 16-bit PCM WAV.")
            if frames <= 0 or frames / rate > max_duration:
                raise TranscriptionError(
                    "Recording is empty or exceeds the duration limit."
                )
            if len(wav.readframes(frames)) != frames * 2:
                raise TranscriptionError("Recording is truncated.")
    except wave.Error, EOFError, OSError, ValueError:
        raise TranscriptionError("Recording is not a valid PCM WAV file.") from None


class AudioTranscriber:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(self, recording: MicrophoneRecorder) -> str:
        """Consume a stopped recorder and delete its audio on every outcome.

        Arbitrary paths are deliberately unsupported. Caller must also own the
        recorder context to cover cancellation before this coroutine starts.
        """
        if not isinstance(recording, MicrophoneRecorder):
            raise TranscriptionError(
                "A completed voice-subsystem recording is required."
            )
        token = private_audio_request.set(True)
        try:
            settings = self.settings
            if not (
                settings.voice_recording_enabled
                and settings.voice_transcription_enabled
            ):
                raise TranscriptionError(
                    "Voice recording and transcription must both be enabled."
                )
            if not settings.openai_api_key.strip():
                raise TranscriptionError("Set OPENAI_API_KEY before transcribing.")
            data = recording.read_recording(settings.voice_transcription_max_bytes)
            _validate_wav(
                data,
                min(
                    settings.voice_max_duration_seconds, recording.max_duration_seconds
                ),
            )
            language = settings.voice_transcription_language
            hints = {}
            # Kyrgyz recognition is experimental; do not send an unverified ky
            # hint. Auto detection lets the service attempt it without promising support.
            if language not in {"auto", "ky"}:
                if settings.voice_transcription_model == "gpt-transcribe":
                    hints["languages"] = [language]
                else:
                    hints["language"] = language
            async with asyncio.timeout(settings.voice_transcription_timeout_seconds):
                async with AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    base_url="https://api.openai.com/v1",
                    timeout=settings.voice_transcription_timeout_seconds,
                    max_retries=0,
                ) as client:
                    with io.BytesIO(data) as audio:
                        result = await client.audio.transcriptions.create(
                            model=settings.voice_transcription_model,
                            file=("recording.wav", audio, "audio/wav"),
                            response_format="json",
                            **hints,
                        )
            if not isinstance(result.text, str) or not result.text.strip():
                raise TranscriptionError("No speech was recognized. Please try again.")
            return result.text.strip()
        except TimeoutError, APITimeoutError:
            raise TranscriptionError(
                "Transcription timed out; no automatic retry was made."
            ) from None
        except APIError:
            raise TranscriptionError(
                "Transcription request failed. Check API access, quota, and connectivity."
            ) from None
        except RecordingError:
            raise TranscriptionError(
                "Recording is unavailable or exceeds the upload limit."
            ) from None
        except TranscriptionError:
            raise
        except Exception:  # noqa: BLE001 - no SDK/transport error details may reach CLI logs
            raise TranscriptionError(
                "Transcription failed safely; please try again."
            ) from None
        finally:
            try:
                recording.close()
            finally:
                private_audio_request.reset(token)
