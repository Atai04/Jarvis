"""Bounded mono int16 capture with an explicitly owned temporary WAV."""

import math
import os
import stat
import threading
import wave
from pathlib import Path
from tempfile import TemporaryDirectory


class RecordingError(RuntimeError):
    """An actionable recording failure, without backend or audio contents."""


class MicrophoneRecorder:
    """Single-use recorder. Use as a context manager to delete the WAV on exit.

    start() opens the default input; stop() returns a WAV valid until close().
    A watchdog releases the device even while the caller is waiting for input.
    Audio callbacks only copy into bounded memory; file IO happens in stop().
    """

    def __init__(self, sample_rate=16000, max_duration_seconds=30, *, backend=None):
        if (
            isinstance(sample_rate, bool)
            or not isinstance(sample_rate, int)
            or not 8000 <= sample_rate <= 192000
        ):
            raise ValueError("Sample rate must be an integer from 8000 to 192000.")
        if (
            isinstance(max_duration_seconds, bool)
            or not isinstance(max_duration_seconds, (int, float))
            or not math.isfinite(max_duration_seconds)
            or not 0.1 <= max_duration_seconds <= 300
        ):
            raise ValueError("Recording duration must be from 0.1 to 300 seconds.")
        self.sample_rate = sample_rate
        self.max_duration_seconds = max_duration_seconds
        self._backend = backend
        self._limit = int(sample_rate * max_duration_seconds) * 2
        self._audio = bytearray()
        self._stream = None
        self._timer = None
        self._temporary = None
        self._path = None
        self._started = False
        self._closed = False
        self._wav_ready = False
        self._error = None
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _capture(self, data, frames, time, status):
        if status:
            self._error = "Audio capture overflowed or failed; please retry."
            raise self._backend.CallbackAbort
        try:
            remaining = self._limit - len(self._audio)
            self._audio.extend(bytes(data)[:remaining])
        except Exception:  # noqa: BLE001 - never leak callback errors to PortAudio stderr
            self._error = "Audio capture failed; please retry."
            raise self._backend.CallbackAbort from None
        if len(self._audio) >= self._limit:
            raise self._backend.CallbackStop

    def start(self):
        if self._started or self._closed:
            raise RecordingError("Create a new recorder for each recording.")
        self._started = True
        try:
            if self._backend is None:
                import sounddevice

                self._backend = sounddevice
            self._temporary = TemporaryDirectory(prefix="jarvis-voice-")
            self._path = Path(self._temporary.name) / "recording.wav"
            device = self._backend.query_devices(kind="input")
            if device["max_input_channels"] < 1:
                raise RecordingError("No microphone input is available.")
            self._backend.check_input_settings(
                channels=1, dtype="int16", samplerate=self.sample_rate
            )
            self._stream = self._backend.RawInputStream(
                channels=1,
                dtype="int16",
                samplerate=self.sample_rate,
                callback=self._capture,
            )
            self._stream.start()
            self._timer = threading.Timer(self.max_duration_seconds, self._finish)
            self._timer.daemon = True
            self._timer.start()
        except BaseException as exc:
            self.close()
            if isinstance(exc, (KeyboardInterrupt, SystemExit, RecordingError)):
                raise
            raise RecordingError(
                "Cannot start microphone. Check the default input device, sample "
                "rate and macOS System Settings > Privacy & Security > Microphone "
                "permission for your terminal or IDE, then restart it."
            ) from None

    def _finish(self):
        with self._lock:
            if self._stream is not None:
                stream, self._stream = self._stream, None
                try:
                    try:
                        stream.abort()
                    finally:
                        stream.close()
                except Exception:  # noqa: BLE001 - watchdog errors reach stop(), not stderr
                    self._error = "Microphone cleanup failed; please restart JARVIS."

    def stop(self) -> Path:
        if not self._started or self._closed:
            raise RecordingError("No recording is active.")
        if self._timer is not None:
            self._timer.cancel()
        self._finish()
        if self._error or not self._audio:
            message = self._error or "No audio received. Check microphone permission."
            self.close()
            raise RecordingError(message)
        try:
            with wave.open(str(self._path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)
                wav.writeframes(self._audio)
        except OSError, wave.Error:
            self.close()
            raise RecordingError("Could not write temporary recording.") from None
        self._wav_ready = True
        return self._path

    def read_recording(self, max_bytes: int) -> bytes:
        """Read only this recorder's completed WAV, bounded and without symlinks.

        Callers receive a snapshot so validation and upload use the same bytes.
        This is an ownership boundary, not a sandbox against in-process code.
        """
        if self._closed or not self._wav_ready:
            raise RecordingError("A completed local recording is required.")
        try:
            descriptor = os.open(
                self._path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            with os.fdopen(descriptor, "rb") as audio:
                metadata = os.fstat(audio.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
                    raise RecordingError(
                        "Recording exceeds the upload limit or is invalid."
                    )
                data = audio.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RecordingError("Recording exceeds the upload limit.")
            return data
        except OSError:
            raise RecordingError("Recording is missing or unreadable.") from None

    def close(self):
        """Release the input and delete audio; safe to call repeatedly."""
        if self._timer is not None:
            self._timer.cancel()
        try:
            self._finish()
        finally:
            self._audio.clear()
            self._closed = True
            if self._temporary is not None:
                self._temporary.cleanup()
