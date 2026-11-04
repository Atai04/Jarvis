"""Context-local suppression of SDK dumps containing private audio or text."""

import logging
from contextvars import ContextVar

private_audio_request = ContextVar("private_audio_request", default=False)


class _PrivateAudioFilter(logging.Filter):
    def filter(self, record):
        return not private_audio_request.get()


for _name in ("openai._base_client", "openai._response"):
    logging.getLogger(_name).addFilter(_PrivateAudioFilter())
