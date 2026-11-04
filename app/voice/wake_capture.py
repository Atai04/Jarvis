"""Bounded, ephemeral wake capture, owned entirely by one worker thread."""

import queue
import threading
import time

from app.voice.wake_detector import PocketSphinxDetector, WakeError


def listen_for_wake(
    phrase: str,
    timeout: float,
    stop: threading.Event,
    *,
    ready: threading.Event | None = None,
    detector_factory=PocketSphinxDetector,
    backend=None,
) -> bool:
    """Return only after microphone AND detector cleanup, including on failure.

    Callback queues at most eight 64 ms frames (16 KiB). Overflow aborts the
    session rather than dropping discontinuous audio into the keyword detector.
    No WAV or recording object is created, so wake audio cannot enter STT.
    """
    samples = queue.Queue(maxsize=8)
    failed = threading.Event()
    stream = None
    detector = None

    def capture(data, frames, timing, status):
        try:
            if status or frames != 1024 or len(data) != 2048:
                failed.set()
                raise backend.CallbackAbort
            if stop.is_set():
                raise backend.CallbackAbort
            samples.put_nowait(bytes(data))
        except queue.Full:
            failed.set()
            raise backend.CallbackAbort from None
        except backend.CallbackAbort:
            raise
        except Exception:  # noqa: BLE001 - callback exceptions must not leak to stderr
            failed.set()
            raise backend.CallbackAbort from None

    try:
        # Both model initialization and native device operations stay off-loop.
        detector = detector_factory(phrase)
        if stop.is_set():
            return False
        if backend is None:
            import sounddevice

            backend = sounddevice
        if backend.query_devices(kind="input")["max_input_channels"] < 1:
            raise WakeError("No microphone input is available.")
        backend.check_input_settings(channels=1, dtype="int16", samplerate=16000)
        stream = backend.RawInputStream(
            channels=1,
            dtype="int16",
            samplerate=16000,
            blocksize=1024,
            callback=capture,
        )
        if stop.is_set():
            return False
        stream.start()
        if ready is not None:
            ready.set()
        deadline = time.monotonic() + timeout
        while not stop.is_set():
            if failed.is_set() or not stream.active:
                raise WakeError(
                    "Wake microphone capture failed; check device access and retry."
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                pcm = samples.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            matched = detector.accept(pcm)
            del pcm
            if failed.is_set():
                raise WakeError("Wake microphone capture overflowed; please retry.")
            if matched:
                return not stop.is_set()
        return False
    finally:
        # A cleanup failure must prevent handoff to a second microphone stream.
        try:
            if stream is not None:
                try:
                    stream.abort()
                finally:
                    stream.close()
        finally:
            try:
                if detector is not None:
                    detector.close()
            finally:
                while not samples.empty():
                    samples.get_nowait()
