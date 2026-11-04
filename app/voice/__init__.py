"""Local-only voice capture; importing this package never opens a device."""

from app.voice.recorder import MicrophoneRecorder, RecordingError

__all__ = ["MicrophoneRecorder", "RecordingError"]
