"""Provider selection; callers only need the asynchronous speak(text) contract."""

import shutil
import sys

from app.config.settings import Settings
from app.voice.openai_tts import OpenAISpeechSynthesizer
from app.voice.tts import SpeechError, SpeechProvider, SpeechSynthesizer


def validate_speech_configuration(settings: Settings) -> None:
    """Check local prerequisites without synthesis, downloads or API requests."""
    if not settings.voice_tts_enabled:
        raise SpeechError("Enable VOICE_TTS_ENABLED before using voice mode.")
    if sys.platform != "darwin":
        raise SpeechError("Voice playback requires macOS.")
    if settings.voice_tts_provider == "macos":
        executables = ["/usr/bin/say"]
    elif settings.voice_tts_provider == "openai":
        if not settings.openai_api_key.strip():
            raise SpeechError("Set OPENAI_API_KEY before using voice mode.")
        executables = ["/usr/bin/afplay"]
        if settings.voice_tts_fallback_to_macos:
            executables.append("/usr/bin/say")
    else:
        raise SpeechError("Unknown speech provider.")
    if any(shutil.which(executable) is None for executable in executables):
        raise SpeechError("Required native speech playback executable is unavailable.")


def build_speech_provider(settings: Settings) -> SpeechProvider:
    if settings.voice_tts_provider == "macos":
        return SpeechSynthesizer(settings)
    if settings.voice_tts_provider == "openai":
        fallback = (
            SpeechSynthesizer(settings)
            if settings.voice_tts_fallback_to_macos
            else None
        )
        return OpenAISpeechSynthesizer(settings, fallback=fallback)
    raise SpeechError("Unknown speech provider.")
