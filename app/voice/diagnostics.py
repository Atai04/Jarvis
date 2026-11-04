"""One content-free event per outer speech attempt, including local fallback."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.logging.logger import logger


@dataclass
class PlaybackAttempt:
    selected_provider: str
    playback_provider: str | None = None
    fallback_occurred: bool = False


_active_attempt = ContextVar("speech_playback_attempt", default=None)


@contextmanager
def speech_attempt(provider: str):
    current = _active_attempt.get()
    if current is not None:
        yield current
        return
    attempt = PlaybackAttempt(provider)
    token = _active_attempt.set(attempt)
    outcome = "failed"
    try:
        yield attempt
        outcome = "success"
    except asyncio.CancelledError, KeyboardInterrupt:
        outcome = "cancelled"
        raise
    finally:
        _active_attempt.reset(token)
        logger.speech_playback(
            selected_provider=attempt.selected_provider,
            playback_provider=attempt.playback_provider,
            fallback_occurred=attempt.fallback_occurred,
            outcome=outcome,
        )
