import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.voice import MicrophoneRecorder, RecordingError
from app.voice.cli import record_command


@pytest.fixture
def audio(monkeypatch):
    timer = Mock()
    monkeypatch.setattr("app.voice.recorder.threading.Timer", timer)
    backend = SimpleNamespace(
        query_devices=Mock(return_value={"max_input_channels": 1}),
        check_input_settings=Mock(),
        RawInputStream=Mock(),
        CallbackAbort=type("CallbackAbort", (Exception,), {}),
        CallbackStop=type("CallbackStop", (Exception,), {}),
    )
    return backend, timer


def test_wav_and_cleanup(audio):
    backend, timer = audio
    with MicrophoneRecorder(8000, 0.1, backend=backend) as recorder:
        recorder.start()
        callback = backend.RawInputStream.call_args.kwargs["callback"]
        callback(b"\x01\x00" * 20, 20, None, False)
        path = recorder.stop()
        with wave.open(str(path)) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (
                1,
                2,
                8000,
            )
            assert wav.getnframes() == 20
            assert wav.readframes(20) == b"\x01\x00" * 20
        assert recorder.stop() == path
        backend.RawInputStream.return_value.close.assert_called_once()
        timer.return_value.cancel.assert_called()
    assert not path.exists()
    assert not path.parent.exists()
    assert not recorder._audio
    recorder.close()


def test_limit_and_watchdog_release_without_user_input(audio):
    backend, timer = audio
    with MicrophoneRecorder(8000, 0.1, backend=backend) as recorder:
        recorder.start()
        with pytest.raises(backend.CallbackStop):
            recorder._capture(b"\x00\x00" * 1000, 1000, None, False)
        assert len(recorder._audio) == 1600
        delay, finish = timer.call_args.args
        assert delay == 0.1
        finish()
        backend.RawInputStream.return_value.abort.assert_called_once()
        backend.RawInputStream.return_value.close.assert_called_once()
        with wave.open(str(recorder.stop())) as wav:
            assert wav.getnframes() == 800


@pytest.mark.parametrize(
    "failure", ["device", "permission", "format", "start", "interrupt"]
)
def test_start_failure_cleans_up(audio, failure):
    backend, _ = audio
    if failure == "device":
        backend.query_devices.return_value = {"max_input_channels": 0}
    elif failure == "permission":
        backend.RawInputStream.side_effect = PermissionError("private backend detail")
    elif failure == "format":
        backend.check_input_settings.side_effect = ValueError("unsupported")
    else:
        backend.RawInputStream.return_value.start.side_effect = (
            KeyboardInterrupt() if failure == "interrupt" else RuntimeError("failed")
        )
    recorder = MicrophoneRecorder(backend=backend)
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else RecordingError):
        recorder.start()
    assert recorder._closed
    assert not recorder._path.parent.exists()
    if failure in {"start", "interrupt"}:
        backend.RawInputStream.return_value.close.assert_called_once()


@pytest.mark.parametrize("failure", ["overflow", "empty", "abort", "close", "write"])
def test_recording_failure_discards_audio(audio, monkeypatch, failure):
    backend, _ = audio
    recorder = MicrophoneRecorder(backend=backend)
    recorder.start()
    if failure == "overflow":
        with pytest.raises(backend.CallbackAbort):
            recorder._capture(b"\0\0", 1, None, True)
    elif failure != "empty":
        recorder._capture(b"\0\0", 1, None, False)
    if failure in {"abort", "close"}:
        getattr(
            backend.RawInputStream.return_value, failure
        ).side_effect = RuntimeError()
    if failure == "write":
        monkeypatch.setattr("app.voice.recorder.wave.open", Mock(side_effect=OSError()))
    with pytest.raises(RecordingError):
        recorder.stop()
    backend.RawInputStream.return_value.close.assert_called_once()
    assert not recorder._path.parent.exists()
    assert not recorder._audio


def test_context_interrupt_and_lifecycle(audio):
    backend, _ = audio
    recorder = MicrophoneRecorder(backend=backend)
    with pytest.raises(RecordingError):
        recorder.stop()
    with pytest.raises(KeyboardInterrupt), recorder:
        recorder.start()
        with pytest.raises(RecordingError):
            recorder.start()
        raise KeyboardInterrupt
    backend.RawInputStream.return_value.close.assert_called_once()
    assert not recorder._path.parent.exists()
    with pytest.raises(RecordingError):
        recorder.start()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate": 0},
        {"sample_rate": 16000.5},
        {"sample_rate": True},
        {"max_duration_seconds": 0},
        {"max_duration_seconds": float("inf")},
        {"max_duration_seconds": float("nan")},
        {"max_duration_seconds": 301},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        MicrophoneRecorder(**kwargs)


def test_settings_defaults_and_validation():
    settings = Settings(_env_file=None)
    assert settings.voice_recording_enabled is False
    assert settings.voice_sample_rate == 16000
    assert settings.voice_max_duration_seconds == 30
    for kwargs in [
        {"voice_sample_rate": 0},
        {"voice_max_duration_seconds": float("nan")},
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **kwargs)


def test_disabled_command_never_constructs_recorder(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not open input"))
    monkeypatch.setattr("app.voice.cli.MicrophoneRecorder", factory)
    record_command(Settings(_env_file=None, voice_recording_enabled=False))
    factory.assert_not_called()


@pytest.mark.parametrize("interruption", [None, KeyboardInterrupt, EOFError])
def test_command_cleanup(audio, monkeypatch, interruption):
    backend, _ = audio
    recorder = MicrophoneRecorder(backend=backend)
    monkeypatch.setattr("app.voice.cli.MicrophoneRecorder", Mock(return_value=recorder))

    def user_input(_):
        recorder._capture(b"\0\0", 1, None, False)
        if interruption:
            raise interruption
        return ""

    monkeypatch.setattr("builtins.input", user_input)
    record_command(Settings(_env_file=None, voice_recording_enabled=True))
    assert recorder._closed
    assert not recorder._path.parent.exists()
    backend.RawInputStream.return_value.close.assert_called_once()


async def test_repl_record_bypasses_agent_and_preserves_text(monkeypatch):
    from unittest.mock import AsyncMock

    from app import main

    settings = Settings(_env_file=None)
    agent = SimpleNamespace(run=AsyncMock(return_value="answer"))
    command = Mock()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "OpenAIProvider", Mock())
    monkeypatch.setattr(main, "build_memory", Mock())
    monkeypatch.setattr(
        main, "build_tool_registry", Mock(return_value=SimpleNamespace(all=list))
    )
    monkeypatch.setattr(main, "AgentOrchestrator", Mock(return_value=agent))
    monkeypatch.setattr(main, "record_command", command)
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=["/record", "hello", "exit"])
    )
    await main.main()
    command.assert_called_once_with(settings)
    agent.run.assert_awaited_once_with("hello")


def test_real_watchdog_closes_idle_mock_device():
    import threading

    closed = threading.Event()
    backend = SimpleNamespace(
        query_devices=Mock(return_value={"max_input_channels": 1}),
        check_input_settings=Mock(),
        RawInputStream=Mock(),
    )
    backend.RawInputStream.return_value.close.side_effect = closed.set
    with MicrophoneRecorder(max_duration_seconds=0.1, backend=backend) as recorder:
        recorder.start()
        assert closed.wait(timeout=2)
        backend.RawInputStream.return_value.close.assert_called_once()
