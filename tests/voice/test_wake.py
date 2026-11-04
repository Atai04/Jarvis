import asyncio
import os
import select
import sys
import termios
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.security.permissions import PermissionEngine, PermissionRequest
from app.voice import wake
from app.voice.wake_capture import listen_for_wake
from app.voice.wake_detector import PocketSphinxDetector, WakeError


def settings(**kwargs):
    return Settings(
        _env_file=None,
        **{
            "voice_wake_enabled": True,
            "voice_recording_enabled": True,
            "voice_transcription_enabled": True,
            "voice_tts_enabled": True,
            "voice_tts_provider": "openai",
            "voice_openai_tts_voice": "cedar",
            "openai_api_key": "unit-key",
            **kwargs,
        },
    )


@pytest.fixture
def session(monkeypatch):
    voice = SimpleNamespace(run=AsyncMock())
    listener = AsyncMock(return_value=True)
    monkeypatch.setattr(wake, "_listen", listener)
    monkeypatch.setattr(wake, "_terminal_fd", lambda: -1)
    monkeypatch.setattr(wake, "validate_speech_configuration", Mock())
    return wake.WakeSession(settings(), voice), listener


def test_defaults_and_phrase(monkeypatch):
    monkeypatch.delenv("VOICE_WAKE_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_WAKE_PHRASE", raising=False)
    config = Settings(_env_file=None)
    assert not config.voice_wake_enabled
    assert config.voice_wake_phrase == "Hey Jarvis"


@pytest.mark.parametrize(
    "field,value",
    [
        ("voice_wake_phrase", "Alexa"),
        ("voice_wake_timeout_seconds", 0),
        ("voice_wake_timeout_seconds", 121),
        ("voice_wake_timeout_seconds", float("nan")),
    ],
)
def test_invalid_configuration(field, value):
    with pytest.raises(ValidationError):
        settings(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "voice_wake_enabled",
        "voice_recording_enabled",
        "voice_transcription_enabled",
        "voice_tts_enabled",
        "openai_api_key",
    ],
)
async def test_disabled_or_incomplete_never_listens(session, field):
    controller, listener = session
    controller.settings = settings(
        **{field: "" if field == "openai_api_key" else False}
    )
    await controller.run()
    listener.assert_not_called()
    controller.voice.run.assert_not_called()
    assert not controller._active


async def test_one_turn_after_terminal_restored(session, monkeypatch):
    controller, listener = session
    events = []

    @contextmanager
    def guard(fd):
        events.append("suppress")
        try:
            yield
        finally:
            events.append("restore")

    async def listen(*args):
        controller.voice.run.assert_not_called()
        events.append("listen")
        return True

    async def voice():
        assert events == ["suppress", "listen", "restore"]

    listener.side_effect = listen
    controller.voice.run.side_effect = voice
    monkeypatch.setattr(wake, "suppress_terminal_input", guard)
    await controller.run()
    listener.assert_awaited_once_with("Hey Jarvis", 30)
    controller.voice.run.assert_awaited_once_with()
    assert not controller._active


@pytest.mark.parametrize(
    "result", [False, RuntimeError("PRIVATE audio"), WakeError("Model unavailable")]
)
async def test_timeout_or_failure_never_runs_voice(session, result, capsys):
    controller, listener = session
    if isinstance(result, Exception):
        listener.side_effect = result
    else:
        listener.return_value = result
    await controller.run()
    controller.voice.run.assert_not_called()
    assert "PRIVATE" not in capsys.readouterr().out
    assert not controller._active


async def test_cancellation_restores_guard_and_state(session, monkeypatch):
    controller, listener = session
    events = []

    @contextmanager
    def guard(fd):
        try:
            yield
        finally:
            events.append("restored")

    monkeypatch.setattr(wake, "suppress_terminal_input", guard)
    listener.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await controller.run()
    assert events == ["restored"]
    assert not controller._active
    controller.voice.run.assert_not_called()


async def test_duplicate_activation_ignored(session):
    controller, listener = session

    async def nested(*args):
        await controller.run()
        return True

    listener.side_effect = nested
    await controller.run()
    listener.assert_awaited_once()
    controller.voice.run.assert_awaited_once()


def audio_backend(frames=1, status=False, channels=1):
    class Abort(Exception):
        pass

    stream = Mock(active=True)
    backend = SimpleNamespace(
        CallbackAbort=Abort,
        query_devices=Mock(return_value={"max_input_channels": channels}),
        check_input_settings=Mock(),
    )

    def create(**kwargs):
        def start():
            for _ in range(frames):
                try:
                    kwargs["callback"](b"\x01\0" * 1024, 1024, None, status)
                except Abort:
                    stream.active = False
                    break

        stream.start.side_effect = start
        return stream

    backend.RawInputStream = Mock(side_effect=create)
    return backend, stream


@pytest.mark.parametrize("matches", [[True], [False, True], [False]])
def test_capture_match_timeout_cleanup_and_model_before_mic(matches):
    backend, stream = audio_backend(frames=len(matches))
    detector = Mock(accept=Mock(side_effect=matches))

    def prepare(phrase):
        assert phrase == "Hey Jarvis"
        backend.RawInputStream.assert_not_called()
        return detector

    assert listen_for_wake(
        "Hey Jarvis", 0.01, threading.Event(), detector_factory=prepare, backend=backend
    ) == any(matches)
    assert detector.accept.call_count == len(matches)
    stream.abort.assert_called_once()
    stream.close.assert_called_once()
    detector.close.assert_called_once()


@pytest.mark.parametrize(
    "problem", ["device", "overflow", "status", "inference", "start", "close"]
)
def test_capture_errors_release_resources(problem):
    backend, stream = audio_backend(
        frames=9 if problem == "overflow" else 1,
        status=problem == "status",
        channels=0 if problem == "device" else 1,
    )
    detector = Mock(accept=Mock(return_value=True))
    if problem == "inference":
        detector.accept.side_effect = RuntimeError("private")
    if problem in {"start", "close"}:
        # create() installs start's normal callback, so patch the factory below.
        original = backend.RawInputStream.side_effect

        def create(**kwargs):
            result = original(**kwargs)
            getattr(result, problem).side_effect = RuntimeError("private")
            return result

        backend.RawInputStream.side_effect = create
    with pytest.raises((WakeError, RuntimeError)):
        listen_for_wake(
            "Hey Jarvis",
            0.01,
            threading.Event(),
            detector_factory=lambda _: detector,
            backend=backend,
        )
    detector.close.assert_called_once()
    if problem != "device":
        stream.close.assert_called_once()


def test_model_failure_never_opens_mic():
    backend, _ = audio_backend()
    with pytest.raises(WakeError):
        listen_for_wake(
            "Hey Jarvis",
            1,
            threading.Event(),
            backend=backend,
            detector_factory=Mock(side_effect=WakeError("unavailable")),
        )
    backend.query_devices.assert_not_called()
    backend.RawInputStream.assert_not_called()


async def test_worker_cancellation_waits_for_microphone_cleanup(monkeypatch):
    entered, released = threading.Event(), threading.Event()

    def listen(phrase, timeout, stop, *, ready):
        entered.set()
        assert stop.wait(2)
        released.set()
        return False

    monkeypatch.setattr(wake, "listen_for_wake", listen)
    task = asyncio.create_task(wake._listen("Hey Jarvis", 30))
    async with asyncio.timeout(2):
        while not entered.is_set():
            await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()


def test_detector_missing_optional_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "pocketsphinx", None)
    with pytest.raises(WakeError, match="uv sync --extra wake"):
        PocketSphinxDetector("Hey Jarvis")


@pytest.mark.parametrize(
    "hypothesis,expected",
    [(None, False), ("hey", False), ("jarvis", False), ("hey jarvis", True)],
)
def test_detector_exact_phrase_and_cleanup(monkeypatch, hypothesis, expected):
    decoder = Mock()
    decoder.hyp.return_value = (
        None if hypothesis is None else SimpleNamespace(hypstr=hypothesis)
    )
    factory = Mock(return_value=decoder)
    monkeypatch.setitem(sys.modules, "pocketsphinx", SimpleNamespace(Decoder=factory))
    detector = PocketSphinxDetector("Hey Jarvis")
    assert detector.accept(b"\0" * 2048) is expected
    factory.assert_called_once_with(
        keyphrase="hey jarvis", samprate=16000, loglevel="FATAL"
    )
    detector.close()
    detector.close()
    decoder.end_utt.assert_called_once()


@pytest.mark.parametrize("missing", ["model", "vocabulary"])
def test_detector_invalid_model_is_sanitized(monkeypatch, missing):
    decoder = Mock()
    decoder.lookup_word.return_value = None
    factory = Mock(return_value=decoder)
    if missing == "model":
        factory.side_effect = RuntimeError("PRIVATE")
    monkeypatch.setitem(sys.modules, "pocketsphinx", SimpleNamespace(Decoder=factory))
    with pytest.raises(WakeError, match="Wake model unavailable") as error:
        PocketSphinxDetector("Hey Jarvis")
    assert "PRIVATE" not in str(error.value)


async def test_cli_explicit_wake_only_and_preserves_voice(monkeypatch):
    from app import main

    agent = SimpleNamespace(run=AsyncMock(return_value="answer"))
    voice = SimpleNamespace(run=AsyncMock())
    controller = SimpleNamespace(run=AsyncMock())
    monkeypatch.setattr(main, "get_settings", settings)
    monkeypatch.setattr(main, "OpenAIProvider", Mock())
    monkeypatch.setattr(main, "build_memory", Mock())
    monkeypatch.setattr(
        main, "build_tool_registry", Mock(return_value=SimpleNamespace(all=list))
    )
    monkeypatch.setattr(main, "AgentOrchestrator", Mock(return_value=agent))
    monkeypatch.setattr(main, "VoiceConversation", Mock(return_value=voice))
    monkeypatch.setattr(main, "WakeSession", Mock(return_value=controller))
    commands = iter(["hello", "/wake", "/voice", "exit"])

    def prompt(_):
        command = next(commands)
        if command == "/wake":
            controller.run.assert_not_called()
        return command

    monkeypatch.setattr("builtins.input", prompt)
    await main.main()
    controller.run.assert_awaited_once_with()
    voice.run.assert_awaited_once_with()
    agent.run.assert_awaited_once_with("hello")


async def test_real_worker_releases_capture_before_one_voice_turn(monkeypatch):
    backend, stream = audio_backend()
    detector = Mock(accept=Mock(return_value=True))

    def listen(phrase, timeout, stop, *, ready):
        return listen_for_wake(
            phrase,
            timeout,
            stop,
            ready=ready,
            backend=backend,
            detector_factory=lambda _: detector,
        )

    async def voice_turn():
        stream.close.assert_called_once()
        detector.close.assert_called_once()

    voice = SimpleNamespace(run=AsyncMock(side_effect=voice_turn))
    monkeypatch.setattr(wake, "listen_for_wake", listen)
    monkeypatch.setattr(wake, "_terminal_fd", lambda: -1)
    monkeypatch.setattr(wake, "validate_speech_configuration", Mock())
    await wake.WakeSession(settings(), voice).run()
    voice.run.assert_awaited_once()


async def test_wake_typeahead_dropped_but_fresh_permission_answer_preserved(
    session, monkeypatch
):
    controller, listener = session
    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    monkeypatch.setattr(wake, "_terminal_fd", lambda: slave)

    async def listen(*args):
        assert not termios.tcgetattr(slave)[3] & termios.ECHO
        os.write(master, b"yes\nexit\n")
        assert select.select([slave], [], [], 1)[0]
        return True

    def prompt(_):
        assert not select.select([slave], [], [], 0)[0]
        os.write(master, b"n\n")
        assert select.select([slave], [], [], 1)[0]
        return os.read(slave, 100).decode()

    async def voice_turn():
        assert termios.tcgetattr(slave) == original
        assert not PermissionEngine().request_confirmation(
            PermissionRequest("test", "benign test", "confirm")
        )

    listener.side_effect = listen
    controller.voice.run.side_effect = voice_turn
    monkeypatch.setattr("builtins.input", prompt)
    try:
        await controller.run()
        controller.voice.run.assert_awaited_once()
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)


async def test_cancel_actual_capture_closes_stream_before_return(monkeypatch):
    backend, stream = audio_backend(frames=0)
    detector = Mock()
    entered = threading.Event()
    stream.start.side_effect = entered.set
    backend.RawInputStream.side_effect = None
    backend.RawInputStream.return_value = stream

    def listen(phrase, timeout, stop, *, ready):
        return listen_for_wake(
            phrase,
            timeout,
            stop,
            ready=ready,
            backend=backend,
            detector_factory=lambda _: detector,
        )

    monkeypatch.setattr(wake, "listen_for_wake", listen)
    task = asyncio.create_task(wake._listen("Hey Jarvis", 30))
    async with asyncio.timeout(2):
        while not entered.is_set():
            await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stream.abort.assert_called_once()
    stream.close.assert_called_once()
    detector.close.assert_called_once()
    detector.accept.assert_not_called()


async def test_readiness_announcement_follows_capture_start(monkeypatch, capsys):
    entered, allow_start, finish = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def listen(phrase, timeout, stop, *, ready):
        entered.set()
        assert allow_start.wait(2)
        ready.set()
        assert finish.wait(2)
        return False

    monkeypatch.setattr(wake, "listen_for_wake", listen)
    task = asyncio.create_task(wake._listen("Hey Jarvis", 30))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        assert "microphone active" not in capsys.readouterr().out
        allow_start.set()
        async with asyncio.timeout(2):
            while "microphone active" not in capsys.readouterr().out:
                await asyncio.sleep(0.001)
        finish.set()
        assert await task is False
    finally:
        allow_start.set()
        finish.set()
        await task
