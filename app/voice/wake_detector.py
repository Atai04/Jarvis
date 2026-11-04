"""Local keyword spotting; no microphone, files written, or network access."""

from typing import Protocol


class WakeError(RuntimeError):
    """Public wake failure; backend messages must not be displayed or logged."""


class WakeDetector(Protocol):
    """A prepared, single-session detector consuming mono 16 kHz int16 PCM.

    Implementations validate/load their local models before capture starts.
    They must not upload, persist, or log samples. close() releases inference
    state; an instance must never be reused for another listening session.
    """

    def accept(self, pcm: bytes) -> bool: ...

    def close(self) -> None: ...


class PocketSphinxDetector:
    def __init__(self, phrase: str):
        if phrase != "Hey Jarvis":
            raise WakeError("Only Hey Jarvis is supported.")
        self._decoder = None
        try:
            from pocketsphinx import Decoder
        except ImportError:
            raise WakeError(
                "Install the optional wake dependency: uv sync --extra wake."
            ) from None
        try:
            # Bundled English acoustic model/dictionary, no language-model search.
            # Leave kws_threshold at the engine's documented/configured default.
            decoder = Decoder(keyphrase="hey jarvis", samprate=16000, loglevel="FATAL")
            if not all(decoder.lookup_word(word) for word in ("hey", "jarvis")):
                raise ValueError("Missing phrase vocabulary")
            decoder.start_utt()
            self._decoder = decoder
        except Exception:  # noqa: BLE001 - sanitize model loading failures
            raise WakeError(
                "Wake model unavailable; check the PocketSphinx installation."
            ) from None

    def accept(self, pcm: bytes) -> bool:
        self._decoder.process_raw(pcm, False, False)
        hypothesis = self._decoder.hyp()
        return hypothesis is not None and hypothesis.hypstr.strip() == "hey jarvis"

    def close(self) -> None:
        decoder, self._decoder = self._decoder, None
        if decoder is not None:
            decoder.end_utt()
