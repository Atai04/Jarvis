import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.voice.cli import speak_command
from app.voice.tts import SpeechError, SpeechSynthesizer


@pytest.fixture
def settings():
    return Settings(_env_file=None, voice_tts_enabled=True)


@pytest.fixture
def process(monkeypatch):
    monkeypatch.setattr("app.voice.tts.sys.platform", "darwin")
    child = SimpleNamespace(
        returncode=0,
        communicate=AsyncMock(return_value=(None, None)),
        wait=AsyncMock(return_value=0),
        terminate=Mock(),
        kill=Mock(),
    )
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr("app.voice.tts.asyncio.create_subprocess_exec", spawn)
    return child, spawn


async def test_success_and_command_safety(settings, process, caplog):
    child, spawn = process
    settings.voice_tts_voice = "Samantha"
    text = "-o /tmp/file; $(touch /tmp/no) `whoami` Привет Merhaba"
    caplog.set_level(logging.DEBUG)
    await SpeechSynthesizer(settings).speak(text)
    spawn.assert_awaited_once_with(
        "/usr/bin/say",
        "-r",
        "175",
        "-v",
        "Samantha",
        "-f",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    child.communicate.assert_awaited_once_with(text.encode("utf-8"))
    child.wait.assert_awaited_once()
    child.terminate.assert_not_called()
    assert text not in caplog.text


async def test_default_voice(settings, process):
    await SpeechSynthesizer(settings).speak("hello")
    assert "-v" not in process[1].call_args.args


@pytest.mark.parametrize(
    "text", ["", "  ", None, "a" * 2001, "[[slnc 999]]", "\0secret", "\x1b[31m"]
)
async def test_invalid_text_never_spawns(settings, process, text):
    with pytest.raises(SpeechError):
        await SpeechSynthesizer(settings).speak(text)
    process[1].assert_not_called()


async def test_disabled_and_other_platform(settings, process, monkeypatch):
    settings.voice_tts_enabled = False
    with pytest.raises(SpeechError, match="disabled"):
        await SpeechSynthesizer(settings).speak("hello")
    settings.voice_tts_enabled = True
    monkeypatch.setattr("app.voice.tts.sys.platform", "linux")
    with pytest.raises(SpeechError, match="macOS"):
        await SpeechSynthesizer(settings).speak("hello")
    process[1].assert_not_called()


@pytest.mark.parametrize(
    "error", [FileNotFoundError, PermissionError, OSError, ValueError]
)
async def test_spawn_failure(settings, process, error):
    process[1].side_effect = error("private payload")
    with pytest.raises(SpeechError) as exc:
        await SpeechSynthesizer(settings).speak("secret")
    assert "private" not in str(exc.value)


async def test_unavailable_voice_or_nonzero_exit(settings, process):
    process[0].returncode = 1
    with pytest.raises(SpeechError, match="installed voice"):
        await SpeechSynthesizer(settings).speak("secret")
    process[0].wait.assert_awaited_once()


async def test_pipe_failure_reaps(settings, process):
    child, _ = process
    child.returncode = None
    child.communicate.side_effect = BrokenPipeError("secret")
    with pytest.raises(SpeechError):
        await SpeechSynthesizer(settings).speak("secret")
    child.terminate.assert_called_once()
    child.wait.assert_awaited_once()


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancellation_and_timeout(settings, process, cancel):
    child, _ = process
    child.returncode = None
    started = asyncio.Event()

    async def communicate(data):
        started.set()
        await asyncio.Future()

    child.communicate.side_effect = communicate
    if not cancel:
        settings.voice_tts_timeout_seconds = 0.01
    synth = SpeechSynthesizer(settings)
    task = asyncio.create_task(synth.speak("hello"))
    await (
        started.wait()
    )  # Playback yields to other tasks, rather than blocking the loop.
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else SpeechError):
        await task
    child.terminate.assert_called_once()
    child.wait.assert_awaited_once()
    assert not synth._speaking


async def test_kill_escalation(settings, process):
    child, _ = process
    child.returncode = None
    child.communicate.side_effect = BrokenPipeError()
    child.wait.side_effect = [TimeoutError(), 0]
    with pytest.raises(SpeechError):
        await SpeechSynthesizer(settings).speak("hello")
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert child.wait.await_count == 2


async def test_cancellation_during_spawn_still_reaps(settings, process):
    child, spawn = process
    child.returncode = None
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(*args, **kwargs):
        entered.set()
        await release.wait()
        return child

    spawn.side_effect = pending
    task = asyncio.create_task(SpeechSynthesizer(settings).speak("hello"))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()  # Repeated cancellation must not abandon the child.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    child.terminate.assert_called_once()
    child.wait.assert_awaited_once()


async def test_overlapping_playback_rejected(settings, process):
    child, _ = process
    child.returncode = None
    started = asyncio.Event()

    async def pending(data):
        started.set()
        await asyncio.Future()

    child.communicate.side_effect = pending
    synth = SpeechSynthesizer(settings)
    task = asyncio.create_task(synth.speak("first"))
    await started.wait()
    with pytest.raises(SpeechError, match="already"):
        await synth.speak("second")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voice_tts_rate": 79},
        {"voice_tts_rate": 451},
        {"voice_tts_rate": 175.5},
        {"voice_tts_max_text_length": 0},
        {"voice_tts_max_text_length": 10001},
        {"voice_tts_timeout_seconds": 0},
        {"voice_tts_timeout_seconds": float("nan")},
        {"voice_tts_voice": ""},
        {"voice_tts_voice": "?"},
        {"voice_tts_voice": "-o"},
        {"voice_tts_voice": "voice\nsecret"},
        {"voice_tts_voice": "a" * 101},
    ],
)
def test_settings_validation(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_settings_defaults_and_env(monkeypatch):
    settings = Settings(_env_file=None)
    assert settings.voice_tts_enabled is False
    assert settings.voice_tts_voice is None
    assert settings.voice_tts_rate == 175
    monkeypatch.setenv("VOICE_TTS_ENABLED", "true")
    monkeypatch.setenv("VOICE_TTS_VOICE", "Samantha")
    monkeypatch.setenv("VOICE_TTS_RATE", "200")
    settings = Settings(_env_file=None)
    assert settings.voice_tts_enabled
    assert settings.voice_tts_voice == "Samantha"
    assert settings.voice_tts_rate == 200


@pytest.mark.parametrize(
    "outcome", ["success", "disabled", "eof", "interrupt", "error", "cancel"]
)
async def test_cli(settings, monkeypatch, capsys, outcome):
    speaker = SimpleNamespace(speak=AsyncMock())
    factory = Mock(return_value=speaker)
    monkeypatch.setattr("app.voice.cli.build_speech_provider", factory)
    prompt = Mock(return_value="private text")
    monkeypatch.setattr("builtins.input", prompt)
    if outcome == "disabled":
        settings.voice_tts_enabled = False
    elif outcome in {"eof", "interrupt"}:
        prompt.side_effect = EOFError if outcome == "eof" else KeyboardInterrupt
    elif outcome == "error":
        speaker.speak.side_effect = SpeechError("Speech unavailable.")
    elif outcome == "cancel":
        speaker.speak.side_effect = asyncio.CancelledError
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await speak_command(settings)
    else:
        await speak_command(settings)
    assert "private text" not in capsys.readouterr().out
    if outcome == "disabled":
        prompt.assert_not_called()
        factory.assert_not_called()
    elif outcome == "success":
        speaker.speak.assert_awaited_once_with("private text")


async def test_repl_speak_is_local_only(monkeypatch):
    from app import main

    agent = SimpleNamespace(run=AsyncMock(return_value="answer"))
    command = AsyncMock()
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main, "OpenAIProvider", Mock())
    monkeypatch.setattr(main, "build_memory", Mock())
    monkeypatch.setattr(
        main, "build_tool_registry", Mock(return_value=SimpleNamespace(all=list))
    )
    monkeypatch.setattr(main, "AgentOrchestrator", Mock(return_value=agent))
    monkeypatch.setattr(main, "speak_command", command)
    monkeypatch.setattr("builtins.input", Mock(side_effect=["/speak", "hello", "exit"]))
    await main.main()
    command.assert_awaited_once()
    agent.run.assert_awaited_once_with("hello")


async def test_child_exits_before_terminate(settings, process):
    child, _ = process
    child.returncode = None
    child.communicate.side_effect = BrokenPipeError()
    child.terminate.side_effect = ProcessLookupError()
    with pytest.raises(SpeechError):
        await SpeechSynthesizer(settings).speak("hello")
    child.wait.assert_awaited_once()


async def test_cleanup_failure_is_sanitized(settings, process):
    child, _ = process
    child.returncode = None
    child.communicate.side_effect = BrokenPipeError()
    child.wait.side_effect = TimeoutError("private detail")
    synth = SpeechSynthesizer(settings)
    with pytest.raises(SpeechError, match="Could not stop") as exc:
        await synth.speak("hello")
    assert "private" not in str(exc.value)
    child.kill.assert_called_once()
    assert not synth._speaking


def test_voice_option_after_whitespace_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, voice_tts_voice=" -o")


async def test_local_playback_diagnostic(settings, process, monkeypatch):
    from app.logging.logger import logger

    log = Mock()
    monkeypatch.setattr(logger, "_write", log)
    await SpeechSynthesizer(settings).speak("private text")
    log.assert_called_once_with(
        event="speech_playback",
        selected_provider="macos",
        playback_provider="macos",
        fallback_occurred=False,
        outcome="success",
    )
