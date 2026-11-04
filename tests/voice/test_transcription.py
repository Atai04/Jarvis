import asyncio
import io
import logging
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import ValidationError

from app.config.settings import Settings
from app.voice import MicrophoneRecorder
from app.voice.cli import transcribe_command
from app.voice.transcription import AudioTranscriber, TranscriptionError


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        openai_api_key="test-only-secret",
        voice_recording_enabled=True,
        voice_transcription_enabled=True,
    )


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setattr("app.voice.recorder.threading.Timer", Mock())
    backend = SimpleNamespace(
        query_devices=Mock(return_value={"max_input_channels": 1}),
        check_input_settings=Mock(),
        RawInputStream=Mock(),
    )
    with MicrophoneRecorder(backend=backend) as recorder:
        recorder.start()
        recorder._capture(b"\x01\x00" * 1600, 1600, None, False)
        path = recorder.stop()
        yield recorder, path


@pytest.fixture
def api(monkeypatch):
    create = AsyncMock(return_value=SimpleNamespace(text=" hello "))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.audio.transcriptions.create = create
    factory = Mock(return_value=client)
    monkeypatch.setattr("app.voice.transcription.AsyncOpenAI", factory)
    return factory, client, create


@pytest.mark.parametrize(
    "language,text",
    [
        ("en", "Hello"),
        ("tr", "Merhaba dünya"),
        ("ru", "Привет мир"),
        ("ky", "Салам дүйнө"),
        ("auto", "Hello / Привет"),
    ],
)
async def test_transcription_languages_and_cleanup(
    settings, capture, api, language, text
):
    settings.voice_transcription_language = language
    recorder, path = capture
    factory, client, create = api

    async def response(**kwargs):
        assert kwargs["file"][0] == "recording.wav"
        assert kwargs["file"][2] == "audio/wav"
        with wave.open(io.BytesIO(kwargs["file"][1].read())) as wav:
            assert wav.getnframes() == 1600
        return SimpleNamespace(text=" " + text + " ")

    create.side_effect = response
    assert await AudioTranscriber(settings).transcribe(recorder) == text
    assert not path.exists()
    client.__aexit__.assert_awaited_once()
    assert create.call_args.kwargs["model"] == "gpt-transcribe"
    assert create.call_args.kwargs["response_format"] == "json"
    assert create.call_args.kwargs["file"][1].closed
    if language in {"auto", "ky"}:
        assert "languages" not in create.call_args.kwargs
    else:
        assert create.call_args.kwargs["languages"] == [language]
    factory.assert_called_once_with(
        api_key="test-only-secret",
        base_url="https://api.openai.com/v1",
        timeout=60,
        max_retries=0,
    )


async def test_legacy_model_language(settings, capture, api):
    settings.voice_transcription_model = "gpt-4o-mini-transcribe"
    settings.voice_transcription_language = "tr"
    await AudioTranscriber(settings).transcribe(capture[0])
    kwargs = api[2].call_args.kwargs
    assert kwargs["language"] == "tr"
    assert "languages" not in kwargs


@pytest.mark.parametrize(
    "failure", ["timeout", "connection", "auth", "rate", "unexpected", "empty"]
)
async def test_safe_failures(settings, capture, api, failure, caplog):
    request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    if failure == "timeout":
        error = APITimeoutError(request=request)
    elif failure == "connection":
        error = APIConnectionError(request=request)
    elif failure in {"auth", "rate"}:
        error_type = AuthenticationError if failure == "auth" else RateLimitError
        error = error_type(
            "private response", response=httpx.Response(401, request=request), body=None
        )
    else:
        error = RuntimeError("private response")
    if failure == "empty":
        api[2].return_value = SimpleNamespace(text=" \n ")
    else:
        api[2].side_effect = error
    with pytest.raises(TranscriptionError) as exc:
        await AudioTranscriber(settings).transcribe(capture[0])
    assert "private response" not in str(exc.value)
    assert "test-only-secret" not in caplog.text
    assert not capture[1].exists()
    api[2].assert_awaited_once()
    api[1].__aexit__.assert_awaited_once()


async def test_task_cancellation(settings, capture, api):
    entered = asyncio.Event()

    async def pending(**kwargs):
        entered.set()
        await asyncio.Future()

    api[2].side_effect = pending
    task = asyncio.create_task(AudioTranscriber(settings).transcribe(capture[0]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not capture[1].exists()
    api[1].__aexit__.assert_awaited_once()


async def test_total_timeout(settings, capture, api):
    settings.voice_transcription_timeout_seconds = 0.01

    async def pending(**kwargs):
        await asyncio.Future()

    api[2].side_effect = pending
    with pytest.raises(TranscriptionError, match="timed out"):
        await AudioTranscriber(settings).transcribe(capture[0])
    assert not capture[1].exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "oversize",
        "garbage",
        "truncated",
        "stereo",
        "width",
        "rate",
        "empty",
        "duration",
        "symlink",
    ],
)
async def test_invalid_files_never_upload(settings, capture, api, tmp_path, failure):
    recorder, path = capture
    if failure == "missing":
        path.unlink()
    elif failure == "oversize":
        settings.voice_transcription_max_bytes = 50
    elif failure == "garbage":
        path.write_bytes(b"not a wav")
    elif failure == "truncated":
        path.write_bytes(path.read_bytes()[:-2])
    elif failure == "duration":
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 8001)
        settings.voice_max_duration_seconds = 1
    elif failure == "symlink":
        other = tmp_path / "other.wav"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    else:
        with wave.open(str(path), "wb") as wav:
            wav.setparams(
                (
                    2 if failure == "stereo" else 1,
                    1 if failure == "width" else 2,
                    4000 if failure == "rate" else 16000,
                    0,
                    "NONE",
                    "not compressed",
                )
            )
            wav.writeframes(b"" if failure == "empty" else b"\0" * 3200)
    with pytest.raises(TranscriptionError):
        await AudioTranscriber(settings).transcribe(recorder)
    api[0].assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize(
    "option",
    ["voice_recording_enabled", "voice_transcription_enabled", "openai_api_key"],
)
async def test_opt_in_required(settings, capture, api, option):
    setattr(settings, option, "" if option == "openai_api_key" else False)
    with pytest.raises(TranscriptionError):
        await AudioTranscriber(settings).transcribe(capture[0])
    api[0].assert_not_called()
    assert not capture[1].exists()


async def test_arbitrary_paths_rejected(settings, capture, api):
    with pytest.raises(TranscriptionError):
        await AudioTranscriber(settings).transcribe(capture[1])
    api[0].assert_not_called()


async def test_unfinished_recorder_rejected(settings, api):
    recorder = MicrophoneRecorder()
    with pytest.raises(TranscriptionError):
        await AudioTranscriber(settings).transcribe(recorder)
    api[0].assert_not_called()
    assert recorder._closed


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voice_transcription_model": "made-up"},
        {"voice_transcription_language": "invalid"},
        {"voice_transcription_max_bytes": 25_000_000},
        {"voice_transcription_max_bytes": 0},
        {"voice_transcription_timeout_seconds": 0},
        {"voice_transcription_timeout_seconds": float("nan")},
    ],
)
def test_configuration_rejected(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_defaults_and_environment(monkeypatch):
    assert Settings(_env_file=None).voice_transcription_enabled is False
    monkeypatch.setenv("VOICE_TRANSCRIPTION_ENABLED", "true")
    monkeypatch.setenv("VOICE_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
    monkeypatch.setenv("VOICE_TRANSCRIPTION_LANGUAGE", "ru")
    settings = Settings(_env_file=None)
    assert settings.voice_transcription_enabled
    assert settings.voice_transcription_model == "gpt-4o-transcribe"
    assert settings.voice_transcription_language == "ru"


@pytest.mark.parametrize("outcome", ["success", "error", "interrupt", "eof", "cancel"])
async def test_cli_cleanup(settings, capture, api, monkeypatch, capsys, outcome):
    recorder, path = capture
    # A genuine recorder with mocked hardware remains the context owner.
    monkeypatch.setattr(recorder, "start", Mock())
    monkeypatch.setattr("app.voice.cli.MicrophoneRecorder", Mock(return_value=recorder))
    interruption = {"interrupt": KeyboardInterrupt, "eof": EOFError}.get(outcome)
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=interruption, return_value="")
    )
    if outcome == "error":
        api[2].side_effect = RuntimeError("private payload")
    elif outcome == "cancel":
        api[2].side_effect = asyncio.CancelledError()
    else:
        api[2].return_value = SimpleNamespace(text="/terminal rm test\x1b[31m")
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await transcribe_command(settings)
    else:
        await transcribe_command(settings)
    output = capsys.readouterr().out
    assert "private payload" not in output
    assert "\x1b" not in output
    assert not path.exists()
    if outcome in {"interrupt", "eof"}:
        api[0].assert_not_called()
    if outcome == "success":
        assert "Recognized text (not executed)" in output


async def test_disabled_cli_never_records(monkeypatch, settings):
    settings.voice_transcription_enabled = False
    factory = Mock()
    monkeypatch.setattr("app.voice.cli.MicrophoneRecorder", factory)
    await transcribe_command(settings)
    factory.assert_not_called()


async def test_sdk_debug_output_is_suppressed(settings, capture, api, caplog):
    async def respond(**kwargs):
        logging.getLogger("openai._base_client").debug("private audio and key")
        logging.getLogger("openai._response").debug("private transcript")
        return SimpleNamespace(text="hello")

    caplog.set_level(logging.DEBUG)
    api[2].side_effect = respond
    await AudioTranscriber(settings).transcribe(capture[0])
    assert "private" not in caplog.text
    logging.getLogger("openai._base_client").debug("ordinary request")
    assert "ordinary request" in caplog.text


async def test_installed_sdk_multipart_without_network(
    settings, capture, monkeypatch, caplog
):
    import httpx2
    from openai import AsyncOpenAI

    calls = []

    async def handle(request):
        calls.append(request)
        body = await request.aread()
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-only-secret"
        assert b'name="model"\r\n\r\ngpt-transcribe' in body
        assert b'name="languages[]"\r\n\r\ntr' in body
        assert b'filename="recording.wav"' in body
        assert b"Content-Type: audio/wav" in body
        assert b"RIFF" in body
        return httpx2.Response(200, json={"text": "Merhaba"})

    transport = httpx2.MockTransport(handle)
    client = httpx2.AsyncClient(transport=transport)
    factory = Mock(
        side_effect=lambda **kwargs: AsyncOpenAI(http_client=client, **kwargs)
    )
    monkeypatch.setattr("app.voice.transcription.AsyncOpenAI", factory)
    settings.voice_transcription_language = "tr"
    caplog.set_level(logging.DEBUG)
    assert await AudioTranscriber(settings).transcribe(capture[0]) == "Merhaba"
    assert len(calls) == 1
    assert client.is_closed
    assert not capture[1].exists()
    assert "test-only-secret" not in caplog.text
    assert "Merhaba" not in caplog.text
    assert "RIFF" not in caplog.text


async def test_repl_transcription_never_dispatches_text(monkeypatch):
    from app import main

    agent = SimpleNamespace(run=AsyncMock(return_value="ordinary answer"))
    command = AsyncMock(return_value="/terminal anything")
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main, "OpenAIProvider", Mock())
    monkeypatch.setattr(main, "build_memory", Mock())
    monkeypatch.setattr(
        main, "build_tool_registry", Mock(return_value=SimpleNamespace(all=list))
    )
    monkeypatch.setattr(main, "AgentOrchestrator", Mock(return_value=agent))
    monkeypatch.setattr(main, "transcribe_command", command)
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=["/transcribe", "hello", "exit"])
    )
    await main.main()
    command.assert_awaited_once()
    agent.run.assert_awaited_once_with("hello")
