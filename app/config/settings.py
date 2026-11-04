from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "JARVIS"
    environment: str = "development"
    log_level: str = "INFO"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.2"
    web_search_enabled: bool = False
    web_search_max_requests_per_turn: int = Field(default=1, ge=0)
    github_token: str = ""
    voice_recording_enabled: bool = False
    voice_sample_rate: int = Field(default=16000, ge=8000, le=192000)
    voice_max_duration_seconds: float = Field(default=30, ge=0.1, le=300)
    voice_transcription_enabled: bool = False
    voice_transcription_model: Literal[
        "gpt-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"
    ] = "gpt-transcribe"
    voice_transcription_language: Literal["auto", "tr", "ru", "ky", "en"] = "auto"
    voice_transcription_max_bytes: int = Field(default=24_000_000, ge=44, le=24_000_000)
    voice_transcription_timeout_seconds: float = Field(default=60, ge=1, le=300)
    voice_tts_enabled: bool = False
    voice_tts_provider: Literal["macos", "openai"] = "macos"
    voice_tts_fallback_to_macos: bool = False
    voice_openai_tts_model: Literal["gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15"] = (
        "gpt-4o-mini-tts"
    )
    voice_openai_tts_voice: Literal[
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "onyx",
        "nova",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    ] = "marin"
    voice_openai_tts_format: Literal["mp3", "wav", "aac"] = "mp3"
    voice_openai_tts_instructions: str | None = Field(
        default=None, max_length=1000, repr=False
    )
    voice_openai_tts_request_timeout_seconds: float = Field(default=60, ge=1, le=300)
    voice_openai_tts_max_audio_bytes: int = Field(
        default=20_000_000, ge=1, le=50_000_000
    )
    voice_tts_voice: str | None = Field(default=None, max_length=100)
    voice_tts_rate: int = Field(default=175, ge=80, le=450)
    voice_tts_max_text_length: int = Field(default=2000, ge=1, le=10000)
    voice_tts_timeout_seconds: float = Field(default=60, ge=1, le=300)

    @field_validator("voice_tts_voice")
    @classmethod
    def validate_tts_voice(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if (
            not value.strip()
            or not value.isprintable()
            or value.startswith("-")
            or "?" in value
        ):
            raise ValueError("Use an installed voice name or omit the voice setting.")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
