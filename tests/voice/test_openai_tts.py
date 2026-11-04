import asyncio
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.voice.cli import speak_command
from app.voice.openai_tts import OpenAISpeechSynthesizer, SpeechGenerationError
from app.voice.providers import build_speech_provider
from app.voice.tts import SpeechError, SpeechSynthesizer

TEXT = "İstanbul’da bugün hava güzel. Çığ, öğün, şüphe, ıhlamur."


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        voice_tts_enabled=True,
        voice_tts_provider="openai",
        openai_api_key="unit-secret",
        voice_openai_tts_instructions="Natural Turkish.",
    )


@pytest.fixture
def mocked(monkeypatch, tmp_path):
    monkeypatch.setattr("app.voice.tts.sys.platform", "darwin")
    monkeypatch.setattr(
        "app.voice.openai_tts.shutil.which", Mock(return_value="/usr/bin/afplay")
    )
    monkeypatch.setattr(
        "app.voice.openai_tts.TemporaryDirectory",
        lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs),
    )

    async def chunks(**kwargs):
        assert kwargs == {"chunk_size": 65536}
        yield b"audio-part-one"
        yield b"audio-part-two"

    response = SimpleNamespace(iter_bytes=Mock(side_effect=chunks))
    stream = AsyncMock()
    stream.__aenter__.return_value = response
    create = Mock(return_value=stream)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.audio.speech.with_streaming_response.create = create
    factory = Mock(return_value=client)
    monkeypatch.setattr("app.voice.openai_tts.AsyncOpenAI", factory)
    child = SimpleNamespace(
        returncode=0, wait=AsyncMock(return_value=0), terminate=Mock(), kill=Mock()
    )

    async def spawn(*args, **kwargs):
        assert args[0] == "/usr/bin/afplay"
        assert Path(args[1]).read_bytes() == b"audio-part-oneaudio-part-two"
        assert Path(args[1]).parent.stat().st_mode & 0o777 == 0o700
        return child

    runner = AsyncMock(side_effect=spawn)
    monkeypatch.setattr("app.voice.openai_tts.asyncio.create_subprocess_exec", runner)
    return SimpleNamespace(
        factory=factory,
        client=client,
        create=create,
        stream=stream,
        response=response,
        runner=runner,
        child=child,
        directory=tmp_path,
    )


def assert_clean(mocked):
    assert list(mocked.directory.iterdir()) == []


async def test_generation_preserves_turkish_and_streams(settings, mocked, caplog):
    caplog.set_level(logging.DEBUG)
    await build_speech_provider(settings).speak(TEXT)
    mocked.create.assert_called_once_with(
        model="gpt-4o-mini-tts",
        voice="marin",
        input=TEXT,
        response_format="mp3",
        instructions="Natural Turkish.",
    )
    mocked.factory.assert_called_once_with(
        api_key="unit-secret",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=60,
    )
    assert mocked.runner.call_args.args[1].endswith(".mp3")
    assert mocked.runner.call_args.kwargs == {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
    }
    mocked.client.__aexit__.assert_awaited_once()
    mocked.stream.__aexit__.assert_awaited_once()
    assert TEXT not in caplog.text
    assert_clean(mocked)


@pytest.mark.parametrize("audio_format", ["mp3", "wav", "aac"])
async def test_format_and_no_instructions(settings, mocked, audio_format):
    settings.voice_openai_tts_format = audio_format
    settings.voice_openai_tts_instructions = None
    await OpenAISpeechSynthesizer(settings).speak(TEXT)
    assert mocked.create.call_args.kwargs["response_format"] == audio_format
    assert "instructions" not in mocked.create.call_args.kwargs
    assert mocked.runner.call_args.args[1].endswith("." + audio_format)
    assert_clean(mocked)


def test_provider_selection_and_defaults(settings):
    defaults = Settings(_env_file=None)
    assert defaults.voice_tts_enabled is False
    assert defaults.voice_tts_provider == "macos"
    assert defaults.voice_tts_fallback_to_macos is False
    assert isinstance(build_speech_provider(defaults), SpeechSynthesizer)
    assert isinstance(build_speech_provider(settings), OpenAISpeechSynthesizer)
    assert build_speech_provider(settings).fallback is None
    settings.voice_tts_fallback_to_macos = True
    assert isinstance(build_speech_provider(settings).fallback, SpeechSynthesizer)


@pytest.mark.parametrize(
    "failure",
    ["disabled", "key", "provider", "length", "api_limit", "platform", "player"],
)
async def test_preflight_never_pays(settings, mocked, monkeypatch, failure):
    text = TEXT
    if failure == "disabled":
        settings.voice_tts_enabled = False
    elif failure == "key":
        settings.openai_api_key = ""
    elif failure == "provider":
        settings.voice_tts_provider = "macos"
    elif failure == "length":
        settings.voice_tts_max_text_length = 1
    elif failure == "api_limit":
        settings.voice_tts_max_text_length = 10000
        text = "a" * 4097
    elif failure == "platform":
        monkeypatch.setattr("app.voice.tts.sys.platform", "linux")
    else:
        monkeypatch.setattr("app.voice.openai_tts.shutil.which", lambda _: None)
    with pytest.raises(SpeechError):
        await OpenAISpeechSynthesizer(settings).speak(text)
    mocked.factory.assert_not_called()
    mocked.runner.assert_not_called()
    assert_clean(mocked)


@pytest.mark.parametrize("fallback", [True, False])
@pytest.mark.parametrize("failure", ["api", "empty", "size", "timeout", "partial"])
async def test_generation_failures_and_fallback(settings, mocked, failure, fallback):
    settings.voice_tts_fallback_to_macos = fallback
    local = SimpleNamespace(speak=AsyncMock())
    if failure == "api":
        mocked.stream.__aenter__.side_effect = RuntimeError("private response " + TEXT)
    else:

        async def chunks(**kwargs):
            if failure == "empty":
                return
            if failure == "size":
                yield b"a" * 20
            elif failure == "partial":
                yield b"partial"
                raise OSError("private body")
            else:
                await asyncio.Future()
                yield b"unreachable"

        mocked.response.iter_bytes.side_effect = chunks
        if failure == "size":
            settings.voice_openai_tts_max_audio_bytes = 10
        if failure == "timeout":
            settings.voice_openai_tts_request_timeout_seconds = 0.01
    provider = OpenAISpeechSynthesizer(settings, fallback=local)
    if fallback:
        await provider.speak(TEXT)
        local.speak.assert_awaited_once_with(TEXT)
    else:
        with pytest.raises(SpeechGenerationError) as exc:
            await provider.speak(TEXT)
        assert "private" not in str(exc.value)
        local.speak.assert_not_called()
    mocked.create.assert_called_once()
    mocked.runner.assert_not_called()
    mocked.client.__aexit__.assert_awaited_once()
    assert_clean(mocked)


@pytest.mark.parametrize("failure", ["exit", "spawn", "timeout"])
async def test_no_fallback_after_playback_attempt(settings, mocked, failure):
    settings.voice_tts_fallback_to_macos = True
    local = SimpleNamespace(speak=AsyncMock())
    if failure == "exit":
        mocked.child.returncode = 1
    elif failure == "spawn":
        mocked.runner.side_effect = FileNotFoundError("private")
    else:
        settings.voice_tts_timeout_seconds = 0.01
        mocked.child.returncode = None
        count = 0

        async def wait():
            nonlocal count
            count += 1
            if count == 1:
                await asyncio.Future()
            return 0

        mocked.child.wait.side_effect = wait
    with pytest.raises(SpeechError):
        await OpenAISpeechSynthesizer(settings, fallback=local).speak(TEXT)
    local.speak.assert_not_called()
    mocked.create.assert_called_once()
    assert_clean(mocked)


@pytest.mark.parametrize("stage", ["download", "playback", "spawn"])
async def test_cancellation_cleanup(settings, mocked, stage):
    settings.voice_tts_fallback_to_macos = True
    local = SimpleNamespace(speak=AsyncMock())
    entered, release = asyncio.Event(), asyncio.Event()
    if stage == "download":

        async def chunks(**kwargs):
            yield b"partial"
            entered.set()
            await asyncio.Future()

        mocked.response.iter_bytes.side_effect = chunks
    elif stage == "spawn":
        mocked.child.returncode = None

        async def spawn(*args, **kwargs):
            entered.set()
            await release.wait()
            return mocked.child

        mocked.runner.side_effect = spawn
    else:
        mocked.child.returncode = None
        count = 0

        async def wait():
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                await asyncio.Future()
            return 0

        mocked.child.wait.side_effect = wait
    provider = OpenAISpeechSynthesizer(settings, fallback=local)
    task = asyncio.create_task(provider.speak(TEXT))
    await entered.wait()
    with pytest.raises(SpeechError, match="already"):
        await provider.speak(TEXT)
    task.cancel()
    if stage == "spawn":
        await asyncio.sleep(0)
        task.cancel()
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    local.speak.assert_not_called()
    if stage != "download":
        mocked.child.terminate.assert_called_once()
    assert not provider._speaking
    assert_clean(mocked)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voice_tts_provider": "other"},
        {"voice_openai_tts_model": "made-up"},
        {"voice_openai_tts_model": "tts-1"},
        {"voice_openai_tts_voice": "unknown"},
        {"voice_openai_tts_format": "pcm"},
        {"voice_openai_tts_format": "opus"},
        {"voice_openai_tts_request_timeout_seconds": 0},
        {"voice_openai_tts_request_timeout_seconds": float("nan")},
        {"voice_openai_tts_max_audio_bytes": 0},
        {"voice_openai_tts_instructions": "a" * 1001},
    ],
)
def test_invalid_settings(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    "voice",
    [
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
    ],
)
def test_supported_voice_configuration(voice):
    assert (
        Settings(_env_file=None, voice_openai_tts_voice=voice).voice_openai_tts_voice
        == voice
    )


async def test_cli_discloses_cloud_and_disabled_never_constructs(
    settings, monkeypatch, capsys
):
    factory = Mock(return_value=SimpleNamespace(speak=AsyncMock()))
    monkeypatch.setattr("app.voice.cli.build_speech_provider", factory)
    prompt = Mock(return_value=TEXT)
    monkeypatch.setattr("builtins.input", prompt)
    await speak_command(settings)
    output = capsys.readouterr().out
    assert "paid API" in output and "AI-generated" in output
    assert TEXT not in output
    factory.return_value.speak.assert_awaited_once_with(TEXT)
    factory.reset_mock()
    settings.voice_tts_enabled = False
    await speak_command(settings)
    factory.assert_not_called()


async def test_real_sdk_streaming_request_and_private_logs(
    settings, mocked, monkeypatch, caplog
):
    import httpx2
    from openai import AsyncOpenAI

    calls = []

    async def handle(request):
        calls.append(request)
        body = json.loads(await request.aread())
        assert request.url.path == "/v1/audio/speech"
        assert body["input"] == TEXT
        assert body["instructions"] == "Natural Turkish."
        assert request.headers["authorization"] == "Bearer unit-secret"
        return httpx2.Response(
            200,
            content=b"audio-part-oneaudio-part-two",
            headers={"content-type": "audio/mpeg"},
        )

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    monkeypatch.setattr(
        "app.voice.openai_tts.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(http_client=client, **kwargs),
    )
    caplog.set_level(logging.DEBUG)
    await OpenAISpeechSynthesizer(settings).speak(TEXT)
    assert len(calls) == 1
    assert client.is_closed
    for private in [TEXT, "Natural Turkish.", "unit-secret", "audio-part-one"]:
        assert private not in caplog.text
    logging.getLogger("openai._base_client").debug("ordinary log remains")
    assert "ordinary log remains" in caplog.text
    assert_clean(mocked)


@pytest.mark.parametrize("failure", [401, 429, 500, "timeout"])
async def test_sdk_errors_do_not_retry_or_log_content(
    settings, mocked, monkeypatch, caplog, failure
):
    import httpx2
    from openai import AsyncOpenAI

    calls = []

    async def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("private timeout " + TEXT, request=request)
        return httpx2.Response(
            failure, json={"error": {"message": TEXT, "type": "test_error"}}
        )

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    monkeypatch.setattr(
        "app.voice.openai_tts.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(http_client=client, **kwargs),
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SpeechGenerationError) as exc:
        await OpenAISpeechSynthesizer(settings).speak(TEXT)
    assert len(calls) == 1
    assert TEXT not in str(exc.value)
    assert TEXT not in caplog.text
    assert "unit-secret" not in caplog.text
    assert client.is_closed
    mocked.runner.assert_not_called()
    assert_clean(mocked)


async def test_real_local_provider_selected_without_api(settings, mocked, monkeypatch):
    settings.voice_tts_provider = "macos"
    child = SimpleNamespace(returncode=0, communicate=AsyncMock(), wait=AsyncMock())
    runner = AsyncMock(return_value=child)
    monkeypatch.setattr("app.voice.tts.asyncio.create_subprocess_exec", runner)
    await build_speech_provider(settings).speak(TEXT)
    assert runner.call_args.args[0] == "/usr/bin/say"
    child.communicate.assert_awaited_once_with(TEXT.encode("utf-8"))
    mocked.factory.assert_not_called()


def test_openai_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "openai")
    monkeypatch.setenv("VOICE_OPENAI_TTS_MODEL", "gpt-4o-mini-tts-2025-12-15")
    monkeypatch.setenv("VOICE_OPENAI_TTS_VOICE", "cedar")
    monkeypatch.setenv("VOICE_OPENAI_TTS_FORMAT", "wav")
    settings = Settings(_env_file=None)
    assert settings.voice_tts_provider == "openai"
    assert settings.voice_openai_tts_model == "gpt-4o-mini-tts-2025-12-15"
    assert settings.voice_openai_tts_voice == "cedar"
    assert settings.voice_openai_tts_format == "wav"


@pytest.mark.parametrize(
    "outcome,used,fallback,status",
    [
        ("success", "openai", False, "success"),
        ("generation_failure", None, False, "failed"),
        ("playback_failure", "openai", False, "failed"),
        ("fallback", "macos", True, "success"),
        ("fallback_failure", "macos", True, "failed"),
        ("cancel", "openai", False, "cancelled"),
    ],
)
async def test_one_accurate_playback_diagnostic(
    settings, mocked, monkeypatch, outcome, used, fallback, status
):
    from app.logging.logger import logger

    log = Mock()
    monkeypatch.setattr(logger, "_write", log)
    settings.voice_tts_fallback_to_macos = fallback
    if outcome in {"generation_failure", "fallback", "fallback_failure"}:
        mocked.stream.__aenter__.side_effect = RuntimeError("private detail")
    if outcome in {"playback_failure", "fallback_failure"}:
        mocked.child.returncode = 1
    if fallback:
        mocked.child.communicate = AsyncMock()
        mocked.runner.side_effect = None
        mocked.runner.return_value = mocked.child
    if outcome == "cancel":
        mocked.child.returncode = None
        mocked.child.wait.side_effect = [asyncio.CancelledError(), 0]
    provider = build_speech_provider(settings)
    if status == "success":
        await provider.speak(TEXT)
    else:
        with pytest.raises(
            asyncio.CancelledError if status == "cancelled" else SpeechError
        ):
            await provider.speak(TEXT)
    log.assert_called_once_with(
        event="speech_playback",
        selected_provider="openai",
        playback_provider=used,
        fallback_occurred=fallback,
        outcome=status,
    )
    assert TEXT not in str(log.call_args)
    assert "private detail" not in str(log.call_args)
    assert_clean(mocked)


async def test_diagnostic_tracks_child_created_during_cancellation(
    settings, mocked, monkeypatch
):
    from app.logging.logger import logger

    log = Mock()
    monkeypatch.setattr(logger, "_write", log)
    entered, release = asyncio.Event(), asyncio.Event()
    mocked.child.returncode = None

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return mocked.child

    mocked.runner.side_effect = spawn
    task = asyncio.create_task(build_speech_provider(settings).speak(TEXT))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    mocked.child.terminate.assert_called_once()
    log.assert_called_once_with(
        event="speech_playback",
        selected_provider="openai",
        playback_provider="openai",
        fallback_occurred=False,
        outcome="cancelled",
    )
    assert_clean(mocked)
