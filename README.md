# JARVIS

## Optional native web search

Web search is disabled by default. To opt in for a process, run:

```sh
WEB_SEARCH_ENABLED=true uv run python -m app.main
```

The existing OpenAI Responses provider adds one native `web_search` tool with
`search_context_size="low"` to requests within the configured turn allowance. Custom function
tools and their permission checks remain in place. No scraping search service or
new dependency is required. Native search definitions supplied by callers are
normalized to one definition when enabled and omitted when disabled.

`LLMResponse.content` retains the original text; `citations` contains source titles,
URLs, and offsets into that text. The CLI displays source URLs inline and stores
that displayed answer in conversation memory. System instructions are explicitly
resent on continuations.

Compatibility was checked against installed OpenAI SDK 3.0.0: its model types
include the unchanged default `gpt-5.2`, and `WebSearchToolParam` supports
`web_search` with `low` context. See the official
[web-search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
and [model documentation](https://developers.openai.com/api/docs/models/gpt-5.2).
Model overrides must support Responses and native web search; API errors propagate
without silently selecting another model. Tests mock all OpenAI requests; account
access and live service behavior have not been tested.

Enabling search authorizes hosted searches within model requests, before local
function-tool permission checks. Queries may disclose conversation information;
retrieved pages are untrusted. Search incurs tool and token charges, and low
context is not a hard spending cap. The existing agent iteration limit does not
limit hosted searches within each response.

## Usage and search safeguards

`WEB_SEARCH_ENABLED` defaults to `false`; ordinary requests do not offer native
search unless you explicitly opt in. `WEB_SEARCH_MAX_REQUESTS_PER_TURN` defaults
to `1` and accepts nonnegative integers. Zero suppresses search even when enabled.
For example, to allow at most two search-enabled model requests per turn:

```sh
WEB_SEARCH_ENABLED=true WEB_SEARCH_MAX_REQUESTS_PER_TURN=2 uv run python -m app.main
```

The initial model request counts toward the limit. Each continuation that offers
search also counts, whether or not the model searches. Once exhausted, subsequent
requests omit native search but retain all custom functions. Each new agent turn
starts a fresh allowance; counters belong to the response chain, not global
provider state. The programmatic `enable_web_search()` opt-in obeys the same limit.

`LLMResponse.usage` preserves API-reported input, output, and total token counts.
The orchestrator emits a `model_usage` structured log event for each returned
model response, linked by the turn's request ID. It includes only those counters,
not prompts, answers, tool results, credentials, or raw responses. Missing counts
are `null`, not zero or estimates. Cached/reasoning token breakdowns are not added
again to the API totals. These are per-response counts, not cumulative balances.

**These safeguards are not a guaranteed monetary spending cap.** The limit counts
application-level model requests offering search, not individual hosted searches
or SDK retry attempts. One response can perform multiple searches. Non-search
requests still consume tokens; failed requests may incur usage that was not
returned. Counters do not estimate prices, query prepaid balance, or enforce a
dollar budget. Existing custom tools (including `open_url`) are unaffected.

## Architecture and startup

JARVIS is a Python 3.14 macOS CLI using an async Responses provider, a custom
function registry, a permission-gated agent loop, SQLite memory and structured
logging. The unchanged default model is `gpt-5.2`.

Configure `OPENAI_API_KEY` and `GITHUB_TOKEN` through your existing local environment
or untracked `.env`; never include credential values in examples or commits.
Startup currently requires both credentials because GitHub tools are always
constructed, even if a turn does not use GitHub. Settings read `.env` relative to
the working directory, so run from the repository root. Startup displays 12 tools:

- macOS/system: `open_application`, `get_system_info`.
- Filesystem/terminal: `list_directory`, `read_file`, `terminal`.
- GitHub read operations: `list_repositories`, `inspect_repository`.
- SQLite: `remember_preference`, `get_preference`, `remember_project`, `get_project`.
- Browser: `open_url`.

Native web search is provider-owned and does not add a registry entry. SAFE tools
run directly, CONFIRM tools prompt, and DANGEROUS tools are denied. This permission
policy is not an OS sandbox. SQLite lives at `data/jarvis.db`; structured logs go
to stderr and `logs/jarvis.log`. Existing argument/error logging is not a complete
secret scrubber: avoid sensitive URL parameters and terminal arguments.

## Browser restrictions

`open_url` pins connections to validated public IPv4 addresses while preserving
Host and HTTPS certificate verification. Redirect destinations are revalidated;
proxy inheritance is disabled. It allows only standard HTTP/HTTPS ports, supported
text formats and uncompressed responses. Limits are three redirects, a 1 MiB body,
a 30-second overall timeout, and 20,000 output characters. IPv6-only or
compressed-only sites may fail by design. HTML remains markup; JavaScript and
subresources are not executed. See [browser security details](app/browser/SECURITY.md)
for the connection-level guarantees and network-routing limitations.

## Verification and manual checks

Run the offline regression suite first (no real OpenAI, GitHub, browser or macOS
actions are needed):

```sh
UV_NO_SYNC=1 UV_OFFLINE=1 uv run ruff check .
UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q
git diff --check
```

Focused checks:

```sh
uv run --no-sync --offline pytest -q tests/llm/test_openai.py tests/test_integration.py
uv run --no-sync --offline pytest -q tests/browser/test_tools.py
```

Tests cover enabled/disabled search, continuation IDs/instructions, citation
metadata/rendering, token counters, per-turn limits, startup registration, real
SQLite persistence, mocked OS/GitHub operations, permission approval/denial, and
browser connection pinning. They do not establish live account access or prove
that a real macOS application opens.

Optional live checks below are for a developer to run deliberately. **Every CLI
turn can incur API charges, even with search disabled.** They were not performed
in this review. Use nonsensitive inputs and already configured credentials:

1. Start with `WEB_SEARCH_ENABLED=false uv run --no-sync python -m app.main`.
   Confirm 12 tools load. Ask for system information, then ask to remember and
   retrieve a harmless preference. These exercise real OS/memory operations only
   if the model chooses the corresponding tools; inspect the tool completion
   events. Do not infer success solely from the assistant's prose.
2. Restart with
   `WEB_SEARCH_ENABLED=true WEB_SEARCH_MAX_REQUESTS_PER_TURN=1 uv run --no-sync python -m app.main`.
   Ask for a current public fact with sources. A successful cited answer should
   display source URLs, and each response should produce a `model_usage` event.
   Search is available, not forced; absence of search is not by itself an API error.
3. To directly verify native search rather than relying on answer text, optionally
   make this single provider request and inspect only output types and counters:

   ```sh
   WEB_SEARCH_ENABLED=true WEB_SEARCH_MAX_REQUESTS_PER_TURN=1 uv run --no-sync python - <<'PY'
   import asyncio
   from app.config.settings import get_settings
   from app.llm.openai import OpenAIProvider

   async def main():
       provider = OpenAIProvider(get_settings())
       try:
           result = await provider.generate(
               "Use web search for current public facts and cite your sources.",
               "What is the latest stable Python release? Search the official website."
           )
           print("Output types:", [item.type for item in result.raw_response.output])
           print("Citation count:", len(result.citations))
           print("Usage:", result.usage)
           print("Search-enabled requests:", result.web_search_requests)
       finally:
           await provider.client.close()

   asyncio.run(main())
   PY
   ```

   `web_search_call` proves the API returned a hosted search item; a counter of one
   only proves search was offered. No search item means this run did not verify
   actual searching. API access errors are not worked around by changing models.
4. Return to `WEB_SEARCH_ENABLED=false` when finished. Check billed usage in your
   account separately; local counters do not enforce a prepaid balance.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for release readiness and remaining work.

## Search execution diagnostics and input-size audit

Each CLI model response now emits `model_diagnostics` beside `model_usage`:

- `web_search_offered`: whether that request included the native tool.
- `web_search_occurred`: whether the response contained a `web_search_call` item.
- `web_search_call_count` and `web_search_completed_count`: output-item counts,
  not billable search counts. A failed/incomplete item counts as an occurrence,
  not a completed search. A custom function named `web_search` does not count.
- `instructions_chars`, `custom_tool_schema_json_chars`, `custom_tool_count`,
  `input_json_chars`, and `continuation`: local request-size metadata. JSON sizes
  use compact serialization and Unicode character counts, not wire bytes or tokens.
  Continuation input size covers newly submitted function results, not inherited
  server-side context.

`model_context` records only memory, conversation and user-message character
counts before initial generation. The user message is already part of conversation
context: these overlapping counts must not be added together as a token estimate.
No queries, retrieved text, source URLs/titles, credentials, or raw request/response
objects are included in these new diagnostic events. Existing tool-argument logs
have the separate privacy limitations described above.

Audit of the reported 14,621 input / 522 output / 15,143 total token run:

- The local usage log confirms those totals and records no custom tool execution
  for that turn. It does not retain native search events or a token breakdown.
- Current system instructions contain 2,372 characters; the 12 function schemas
  contain 5,588 characters in compact JSON. The recorded user message is 68
  characters. These are **not** token counts, and historical memory context was
  not measured. No tokenizer dependency was added or remote count request made.
- Hosted search can supply additional context. The API's aggregate usage does not
  attribute input tokens to instructions, schemas, memory or retrieved passages.
  A large hosted-search contribution is plausible, not an established exact
  breakdown. Links alone do not retrospectively prove a native search call.
- `low` search context is guidance, not a token ceiling. On continuations, inherited
  context also counts toward API usage despite the short local input. See the
  official [search context documentation](https://developers.openai.com/api/docs/guides/tools-web-search)
  and [conversation-state documentation](https://developers.openai.com/api/docs/guides/conversation-state).

The renderer now leaves existing source links intact and inserts each missing
annotation URL at most once. It preserves raw answer text and citation metadata;
intentional repeated links already authored by the model are not rewritten. Old
conversation records are not modified. The lone-message conversation wrapper was
removed, saving 54 characters per initial request without removing memory or tools.

For lower usage, leave search off for non-current tasks and retain a small request
allowance. Future optimizations should measure schema/instruction changes and add
an explicit focused-search mode before omitting tools; silently dropping tools or
memory could change behavior. Model changes, output-token caps and hosted-tool
call caps were not introduced here. No exact monetary savings or cap is claimed.

## Local microphone recording (opt-in)

Voice capture is disabled by default. `/record` is handled locally before agent
routing: it never invokes the model, uploads audio, or stores conversation memory.
Other text commands retain their existing behavior. `/record` does not transcribe;
the separate opt-in `/transcribe` and local `/speak` workflows are described below.
There is no wake word or automatic voice conversation loop. Recording configuration:

| Environment variable | Default | Accepted values |
| --- | --- | --- |
| `VOICE_RECORDING_ENABLED` | `false` | Boolean |
| `VOICE_SAMPLE_RATE` | `16000` | Integer, 8000–192000 Hz; device must support it |
| `VOICE_MAX_DURATION_SECONDS` | `30` | 0.1–300 seconds |

Run a recording-only check without API credentials or requests:

```sh
VOICE_RECORDING_ENABLED=true uv run python -m app.voice.cli
```

Speak, then press Enter to stop. Ctrl-C or EOF cancels. The microphone is closed
automatically at the duration limit even if Enter has not been pressed; the prompt
still waits for Enter. The command writes a temporary mono 16-bit PCM WAV, then
deletes it. No playback or persistent copy is made automatically. In the regular
CLI, enable the same setting and type `/record` explicitly. Ordinary text turns
can still incur API charges; the standalone command avoids agent startup entirely.

On macOS, accept the microphone prompt for the application hosting Python
(Terminal, iTerm, or your IDE). If denied, open **System Settings > Privacy &
Security > Microphone**, enable that application, then fully quit and reopen it.
Check **System Settings > Sound > Input** for the desired default microphone.
If the host application is absent from the permission list, run the explicit
recording command to trigger a request. Some hosts may not forward the prompt;
try Terminal. Unsupported rates, absent devices, permission failures and empty
capture are reported without backend details. Permission denial can also produce
silent samples on some systems, so a successful WAV alone does not prove audibility.

To listen deliberately while the temporary WAV exists (no API calls):

```sh
uv run python - <<'PY'
import subprocess
from app.voice import MicrophoneRecorder

with MicrophoneRecorder(sample_rate=16000, max_duration_seconds=5) as recorder:
    recorder.start()
    input("Speak, then press Enter (capture stops after five seconds): ")
    path = recorder.stop()
    subprocess.run(["afplay", str(path)], check=True)
assert not path.exists()
PY
```

The programmatic API is an explicit opt-in independent of CLI settings. Always
use its context manager (or `close()` in `finally`): `start()` opens input,
`stop()` closes input and returns a temporary WAV path, and context exit deletes
it. Each recorder is single-use. Audio is bounded in memory during capture and
written only on successful stop into a private temporary directory. Overflow is
an error rather than silently accepting dropped audio. Forced termination or an
OS crash can leave temporary files; cleanup is guaranteed only during normal
Python unwinding, not SIGKILL. Device/driver failures can prevent OS cleanup.

Dependency choice: [sounddevice](https://pypi.org/project/sounddevice/) provides
macOS wheels bundling PortAudio; its
[raw streams](https://python-sounddevice.readthedocs.io/en/latest/api/raw-streams.html)
need no NumPy. [CFFI](https://pypi.org/project/cffi/) provides Python 3.14 support.
Locally verified on CPython 3.14.1: sounddevice 0.5.6, CFFI 2.1.1, and PortAudio
19.7 load successfully without opening a device. Hardware capture and permission
prompts require the manual checks above; automated tests use mocked devices only.

## Opt-in OpenAI speech transcription

`/transcribe` records fresh audio, uploads it to OpenAI, and displays the recognized
text. **It can incur API charges and sends audio off-device.** Both recording and
transcription must be enabled, and the command must be explicitly invoked. It
never passes the transcript to the agent, tools, conversation memory or application
logs. `/record` remains local-only, even when transcription is enabled.

The default is `gpt-transcribe`, recommended by the current official
[file transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text)
and listed in the [model catalog](https://developers.openai.com/api/docs/models/gpt-transcribe).
Compatibility was checked against installed OpenAI Python SDK 3.0.0: its async
`audio.transcriptions.create` supports the model, JSON output, multipart WAV,
and plural `languages` hints. A real SDK request is tested through a mocked HTTP
transport, with no network. Account access and live recognition remain unverified.
No dependencies or credentials were added; this uses the existing `OPENAI_API_KEY`.

| Environment variable | Default | Values |
| --- | --- | --- |
| `VOICE_TRANSCRIPTION_ENABLED` | `false` | Boolean; also requires `VOICE_RECORDING_ENABLED=true` |
| `VOICE_TRANSCRIPTION_MODEL` | `gpt-transcribe` | `gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` |
| `VOICE_TRANSCRIPTION_LANGUAGE` | `auto` | `auto`, `tr`, `ru`, `en`, `ky` |
| `VOICE_TRANSCRIPTION_MAX_BYTES` | `24000000` | 44–24000000 bytes; below the API's 25 MB limit |
| `VOICE_TRANSCRIPTION_TIMEOUT_SECONDS` | `60` | 1–300 seconds; total async deadline and SDK timeout |

The two legacy model overrides use singular `language` hints. They are deprecated
and scheduled to shut down February 26, 2027; prefer the default. See OpenAI's
[deprecation notice](https://developers.openai.com/api/docs/deprecations).
Turkish (`tr`), Russian (`ru`) and English (`en`) can use explicit language hints
or automatic detection. Kyrgyz (`ky`) is an experimental selection that deliberately
uses automatic detection: current docs do not establish acceptance of a `ky` hint
or recognition quality. No equal accuracy or guaranteed Kyrgyz recognition is
claimed. Tests using Kyrgyz strings verify Unicode handling, not model accuracy.

Manual test (deliberately billable; not run during development):

1. Configure the existing `OPENAI_API_KEY` in your environment or untracked `.env`.
   Grant the host terminal/IDE microphone permission as described above.
2. Run the standalone workflow; it needs no GitHub credential and never starts
   the reasoning agent:

   ```sh
   VOICE_RECORDING_ENABLED=true VOICE_TRANSCRIPTION_ENABLED=true \
   VOICE_TRANSCRIPTION_LANGUAGE=tr uv run python -m app.voice.cli --transcribe
   ```

3. Speak a short nonsensitive sentence, then press Enter to stop and upload.
   Confirm the recognized text appears under `Recognized text (not executed)`.
   Repeat deliberately with `ru`, `en`, or experimental `ky` to assess accuracy.
   Ctrl-C or EOF before upload cancels without a request. During upload, Ctrl-C
   cancels local processing, but cannot undo audio already sent or charges incurred.
4. Alternatively, enable the same settings in the regular CLI and type
   `/transcribe`. A spoken command is displayed only, never executed.
5. Return `VOICE_TRANSCRIPTION_ENABLED=false` when done. A disabled invocation
   must not open a microphone or make a request.

The component accepts a stopped `MicrophoneRecorder`, not arbitrary file paths.
It checks lifecycle, file existence/type, byte limit, RIFF/WAV structure, mono
16-bit PCM, sample rate, nonempty complete frames and duration (using the smaller
of the recorder and current configured limits). Validation and upload share the
same bounded bytes snapshot; symlink inputs are rejected. The recorder context
owns cleanup, and the transcriber also closes it on success, errors or cancellation.
This ownership API is not a sandbox against malicious code within the same process.

SDK retries are disabled: failures and timeouts require another explicit recording.
Errors are summarized without response bodies, audio, transcripts or credentials.
SDK request/error debug dumps are suppressed within the transcription task even
if SDK debug logging is enabled. Transcripts are shown only on stdout, with terminal
control characters removed; terminal scrollback or externally redirected stdout
can still retain displayed text. Cleanup deletes local temporary files, not
provider-side data; Python cannot guarantee cleanup after SIGKILL or an OS crash.
The duration watchdog releases the microphone while the Enter prompt may remain.

## Native macOS text-to-speech (opt-in)

With the default `VOICE_TTS_PROVIDER=macos`, `/speak` prompts for text and plays it
locally through `/usr/bin/say`. This provider never
speaks agent responses automatically, starts a microphone, calls an API, or sends
text to the agent or tools. TTS is independent of recording/transcription settings
and disabled by default. No new dependencies or API costs are introduced.

| Environment variable | Default | Values |
| --- | --- | --- |
| `VOICE_TTS_ENABLED` | `false` | Boolean |
| `VOICE_TTS_VOICE` | unset | Installed voice name; unset uses the macOS default |
| `VOICE_TTS_RATE` | `175` | 80–450 words per minute |
| `VOICE_TTS_MAX_TEXT_LENGTH` | `2000` | 1–10000 characters; longer text is rejected |
| `VOICE_TTS_TIMEOUT_SECONDS` | `60` | 1–300 seconds |

List installed voices without playing speech:

```sh
/usr/bin/say -v '?'
```

Test playback without API credentials or agent startup:

```sh
VOICE_TTS_ENABLED=true uv run python -m app.voice.cli --speak
```

Enter a short, nonsensitive sentence and press Enter. Check the selected macOS
sound output and volume. To choose a voice, use its exact name from the list:

```sh
VOICE_TTS_ENABLED=true VOICE_TTS_VOICE='Samantha' VOICE_TTS_RATE=180 \
uv run python -m app.voice.cli --speak
```

Use a voice actually installed on your Mac; the example name is not guaranteed
available. Missing/unusable voices and other nonzero `say` exits produce a safe
error without exposing native diagnostics. Voice availability, language coverage,
pronunciation and rate behavior depend on macOS and the installed voice. Nothing
is downloaded automatically by JARVIS. Invocation details were verified against
the local `man say` documentation; audible playback was not tested in development.

In the regular CLI, enable `VOICE_TTS_ENABLED=true` and enter `/speak`, then enter
the text at its separate prompt. The command is not sent to the model or saved in
conversation memory. The regular CLI still needs its existing startup credentials;
use the standalone command above to avoid agent startup. Ctrl-C before playback
cancels input. Ctrl-C during playback stops speech and may exit the CLI. For a
manual timeout check, use `VOICE_TTS_TIMEOUT_SECONDS=1` and a sentence that takes
several seconds to speak. Restore `VOICE_TTS_ENABLED=false` when finished.

Programmatically, `await SpeechSynthesizer(settings).speak(text)` yields to the
event loop during playback. To stop, cancel its task and await it, handling
`asyncio.CancelledError`. Cancellation and timeout terminate and reap the owned
process; after a one-second grace period it is killed, with another one-second
wait. Cleanup is shielded against repeated task cancellation, including during
process creation. Concurrent calls on the same synthesizer are rejected. The
interactive CLI waits for completion before its next prompt, while the underlying
playback is asynchronous. Forced application termination cannot guarantee cleanup.

Text goes through stdin, never shell execution or command arguments. Native
stdout/stderr are discarded; errors and application logs do not include spoken
text. No audio files are created. Plain text is required: native `[[...]]` speech
markup and control characters are rejected. Input still appears in the terminal
as you type, and audible speech can be heard by others; terminal capture is outside
application logging controls. Automated tests mock all subprocesses and exercise
success, errors, privacy, command safety, timeouts and cancellation without playback.

## Optional OpenAI neural TTS provider

The default remains local `macos`, with all existing `say` settings preserved.
`build_speech_provider(settings)` returns a provider with `async speak(text)`;
`SpeechSynthesizer(settings)` remains the existing explicit macOS implementation.
`/speak` and the standalone `--speak` command use the selected provider. Ordinary
text-chat responses are not spoken; the explicit `/voice` interaction below speaks
its final response. The reasoning model is unchanged.

**Availability checked November 4, 2026:** the requested Audio Speech API and
installed OpenAI SDK 3.0.0 support the two mini TTS models below, style instructions,
streaming binary responses and the listed voices. However, these models are
**deprecated and scheduled to shut down January 6, 2027**. The recommended
replacement uses the Realtime API, not `/v1/audio/speech`; changing only the model
name will not migrate this provider. See the official
[Speech API reference](https://developers.openai.com/api/reference/python/resources/audio/subresources/speech/methods/create)
and [deprecation notice](https://developers.openai.com/api/docs/deprecations).
Account access was not tested. This implementation follows the requested Speech
API scope; it does not add a Realtime session or continuous conversation loop.

| Environment variable | Default | Values / behavior |
| --- | --- | --- |
| `VOICE_TTS_ENABLED` | `false` | Required for either provider |
| `VOICE_TTS_PROVIDER` | `macos` | `macos` or explicit `openai` |
| `VOICE_OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` | Also `gpt-4o-mini-tts-2025-12-15` |
| `VOICE_OPENAI_TTS_VOICE` | `marin` | Built-in voice list below |
| `VOICE_OPENAI_TTS_FORMAT` | `mp3` | `mp3`, `wav`, `aac` for native file playback |
| `VOICE_OPENAI_TTS_INSTRUCTIONS` | unset | Optional speaking style, maximum 1000 characters |
| `VOICE_OPENAI_TTS_REQUEST_TIMEOUT_SECONDS` | `60` | 1–300 seconds for the complete download |
| `VOICE_OPENAI_TTS_MAX_AUDIO_BYTES` | `20000000` | 1–50000000; abort larger downloads |
| `VOICE_TTS_FALLBACK_TO_MACOS` | `false` | Optional local fallback on generation failure only |

Existing `VOICE_TTS_MAX_TEXT_LENGTH` applies to both providers. OpenAI additionally
rejects inputs over 4096 characters; input is never split into extra paid requests.
Existing `VOICE_TTS_TIMEOUT_SECONDS` bounds playback independently of generation.
`VOICE_TTS_VOICE` and `VOICE_TTS_RATE` still configure only macOS speech, including
fallback. The supported mini models accept style instructions; older `tts-1`
models are intentionally not exposed. Unsupported models, voices and formats fail
settings validation. Raw PCM and Opus are not offered through this native file
playback path. No new Python dependencies are required.

Supported built-in voice identifiers: `alloy`, `ash`, `ballad`, `coral`, `echo`,
`fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`, `marin`, `cedar`. Discover the
current list and previews in the official
[TTS voice guide](https://developers.openai.com/api/docs/guides/text-to-speech#voice-options).
These are API voice names, separate from `/usr/bin/say -v '?'`. The guide recommends
`marin` and `cedar` for quality and lists Turkish among supported languages, while
noting that voices are optimized for English. Evaluate pronunciation on your own
sentences; equal quality, accent-free or human-identical speech is not guaranteed.
The mini model is chosen for economical speech generation with style control,
not as a promise of the lowest possible price or a fixed cost cap.

Manual local test (no API call):

```sh
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=macos \
uv run python -m app.voice.cli --speak
```

Manual OpenAI test (**paid**, not performed during development): configure the
existing `OPENAI_API_KEY` in your environment or untracked `.env`, then run:

```sh
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=openai \
VOICE_OPENAI_TTS_MODEL=gpt-4o-mini-tts VOICE_OPENAI_TTS_VOICE=marin \
VOICE_OPENAI_TTS_FORMAT=mp3 \
VOICE_OPENAI_TTS_INSTRUCTIONS='Speak natural, fluent Turkish with clear pronunciation, conversational pacing, and a warm, professional assistant tone.' \
uv run python -m app.voice.cli --speak
```

At the prompt enter, for example:

```text
Merhaba! Bugün İstanbul'da hava güzel. Size nasıl yardımcı olabilirim?
```

Listen for Turkish characters, names, punctuation, pacing and warmth. Repeat
explicitly with `VOICE_OPENAI_TTS_VOICE=cedar` or another supported voice to compare.
Each run can incur charges. The application sends the original input unchanged,
with style instructions as a separate parameter; it does not translate or
paraphrase. A generative model's spoken rendering may still vary. The CLI clearly
labels OpenAI playback as AI-generated. The same configuration works with `/speak`
in the main CLI, which retains its existing startup credential requirements.

Audio is streamed in 64 KiB chunks into a private temporary directory, capped by
size and request duration. Playback begins only after download and resource closure,
using `/usr/bin/afplay` without a shell. Text is not placed in process arguments.
Audio is deleted after success, failure or cancellation; no persistent cache is
created. Playback cancellation uses the existing shielded terminate/kill/reap
cleanup. Ctrl-C stops local work but cannot undo a request already sent or charges.
Force-killing Python or OS/driver failures can prevent cleanup. Audible playback,
codec behavior, live API access and Turkish quality still require manual testing.

SDK retries are disabled. Generation failures (API errors, timeout, empty/oversized
or interrupted downloads) may use local fallback only when
`VOICE_TTS_FALLBACK_TO_MACOS=true`. Fallback does not make another API request, and
never occurs after a playback attempt, on task cancellation, or for invalid input,
missing credentials or missing playback prerequisites. This avoids replaying speech
that may already have been heard. A failed local fallback reports an error. Voice
character and pronunciation may change when falling back; the CLI announces the
fallback policy before input. No fallback is silently enabled.

OpenAI sends text and optional instructions to an external paid service using the
existing credential and fixed OpenAI API URL. Local file deletion does not erase
provider-side data. There is no application logging of text, instructions, audio
bytes or credentials; context-local filters also suppress sensitive SDK debug dumps
for transcription and speech generation. Terminal input/scrollback and audible
output retain the privacy limitations described above. Disable with
`VOICE_TTS_ENABLED=false`, or return to `VOICE_TTS_PROVIDER=macos` for local speech.

## One-shot push-to-talk conversation: `/voice`

`/voice` performs exactly one recording → transcription → existing agent turn →
speech playback. It then returns to idle; another recording requires another
explicit `/voice`. There is no wake word, continuous listening or background
microphone activation. Text chat, `/record`, `/transcribe` and `/speak` retain their
existing behavior. No dependencies, credentials or reasoning-model changes were
introduced.

All three settings must be enabled: `VOICE_RECORDING_ENABLED`,
`VOICE_TRANSCRIPTION_ENABLED`, and `VOICE_TTS_ENABLED`. Before opening a microphone,
the controller checks these flags, the existing API key, an interactive terminal,
macOS and the selected native playback executables. Device permission and installed
voice availability may still fail at runtime. Existing size, duration, text-length,
request-timeout and playback-timeout limits remain in effect.

Manual test with OpenAI Cedar and explicitly enabled local Yelda fallback:

```sh
cd ~/jarvis
VOICE_RECORDING_ENABLED=true VOICE_TRANSCRIPTION_ENABLED=true \
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=openai \
VOICE_OPENAI_TTS_MODEL=gpt-4o-mini-tts VOICE_OPENAI_TTS_VOICE=cedar \
VOICE_TTS_VOICE=Yelda VOICE_TTS_FALLBACK_TO_MACOS=true \
VOICE_TRANSCRIPTION_LANGUAGE=tr VOICE_MAX_DURATION_SECONDS=15 \
WEB_SEARCH_ENABLED=false \
uv run python -m app.main
```

Configure `OPENAI_API_KEY` and the existing startup-required `GITHUB_TOKEN` in your
local environment or untracked `.env`; do not put credentials in the command.
Check `/usr/bin/say -v '?'` for Yelda before relying on local fallback. The main
CLI must run in an interactive macOS terminal, not piped stdin or a notebook.
Grant microphone permission to that terminal/IDE as described above.

1. Type `/voice`. Confirm `Recording` appears, then speak a harmless short request,
   such as “Merhaba, bana kısa bir selamlama yap.”
2. Press Enter to stop, or wait for the duration limit. In `/voice`, reaching the
   limit advances immediately; it does not leave an Enter prompt waiting.
3. Confirm the states `Transcribing`, `Processing`, `Speaking`, and `Completed`.
   Inspect the displayed transcript and final response. After playback the
   microphone must remain idle until another explicit `/voice`.
4. Test a benign tool request that requires confirmation. Read the action and type
   `n` at the existing permission prompt to deny it. Spoken “yes” is not approval.
   The microphone and recording input reader are closed before agent processing.
5. Press Ctrl-C during recording or playback to test cancellation. It releases voice
   resources, but can exit the CLI rather than return to its prompt. Restart if needed.

For local speech output instead, use:

```sh
VOICE_RECORDING_ENABLED=true VOICE_TRANSCRIPTION_ENABLED=true \
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=macos VOICE_TTS_VOICE=Yelda \
VOICE_TRANSCRIPTION_LANGUAGE=tr WEB_SEARCH_ENABLED=false \
uv run python -m app.main
```

Then type `/voice`. This still uses paid transcription and reasoning; only speech
synthesis is local. OpenAI speech uses the configured fallback policy unchanged:
there is no fallback on cancellation or after a playback attempt, and no paid TTS
retry. The Speech API model shutdown noted above still applies. Live account access,
Turkish pronunciation and actual microphone/playback behavior were not tested.

### Permissions, memory, privacy and costs

The transcript is forwarded once as **user input** to the same `agent.run()` used
by typed chat. It is never passed directly to a shell, treated as a system prompt,
or interpreted as `/voice`, `/speak`, or another CLI command. Existing SAFE/CONFIRM/
DANGEROUS decisions, typed confirmations, agent iteration limits and web-search
allowances remain in force. There is no voice-specific approval path. This preserves
the existing security boundary; it does not prove immunity to prompt injection or
misrecognition. SAFE tools can run without an extra confirmation, just as in text
chat. Read any proposed sensitive action before approving it.

One activation makes at most one STT request, one call to the orchestrator (which
can make its existing reasoning/tool-continuation requests), and one speech-provider
call. Existing reasoning SDK retry behavior remains unchanged. Search/tool costs
may also apply. Cancelling cannot undo requests already sent, incurred charges,
completed tool actions, or memory writes. Existing tools can have their own execution
lifetimes; voice cancellation is not a transaction rollback or tool-process sandbox.

Input WAVs and generated audio remain temporary and are deleted during normal
success, failure and cancellation cleanup. The recorder's watchdog and the async
terminal reader end at the duration limit. The reader is removed and queued terminal
input is flushed before any later tool confirmation; no background `input()` thread
can consume a confirmation. Ctrl-C during asynchronous work propagates cancellation
after cleanup. SIGKILL, OS failure and native driver/process failures can defeat
cleanup guarantees.

**Transcripts and final responses are persisted in the existing SQLite conversation
memory**, just like typed turns. Persistent preferences and the orchestrator's current
context behavior are retained; this feature does not change how prior conversations
are selected. Transcript/response display is deliberate and can remain in terminal
scrollback. They may contain private information, and OpenAI TTS sends the final
response (potentially including tool results) to OpenAI. Use local TTS when that
additional disclosure is unwanted.

During a voice turn, SDK debug request/error dumps are suppressed and structured
logs omit tool arguments and free-form tool errors; operational counters and status
remain. Raw audio and full transcripts are not logged by this workflow. Normal text
chat retains its existing logging behavior and limitations. Local deletion and log
suppression do not erase SQLite memory, terminal capture or remote API data.

STT failure or an empty transcript prevents agent execution. Agent failure prevents
speech. TTS failure leaves the already displayed text response available, including
when the response exceeds speech length limits or contains unsupported speech markup.
No automatic truncation, summarization, second reasoning call or new recording is
introduced to work around speech failure.

### Terminal input during `/voice`

After recording stops, `/voice` hides keyboard echo and discards typeahead during
transcription, agent processing, speech generation and playback. Wait for `You >`
before typing another command. Typing `exit`, `q`, or blank lines during playback
will not queue commands for the next prompt. `q` is not a JARVIS quit command;
use `exit` or `quit` at `You >`. Once JARVIS exits, typed commands belong to your shell.

The existing typed permission prompt temporarily restores normal terminal input
and echo **before displaying the request**. Input queued before that prompt is
discarded, but your answer entered at the prompt is read normally. After the answer,
voice processing resumes with input suppressed. No extra stdin reader or background
input thread is installed. Ctrl-C remains enabled. On success, failure or cancellation,
the terminal's original modes are restored and pending input is flushed. The main
CLI handles cancellation/EOF with one Goodbye message rather than repeated prompts
or a cancellation traceback. Ctrl-C during asynchronous `/voice` work exits the CLI.

This operates on the POSIX terminal input queue. It is intended for interactive
macOS terminals, not IDE input emulators, redirected stdin or notebook consoles.
Type only after the corresponding prompt; input arriving after a state transition
belongs to the new state. Terminal suspension, SIGKILL, or terminal disconnection
can prevent restoration; if echo remains disabled after abnormal termination, run
`stty sane` in the shell. Cancellation cannot undo completed tool actions or charges.

### Playback diagnostics and regression check

Each outer TTS attempt emits one structured `speech_playback` event, including when
local fallback is used. Fields are `selected_provider`, `playback_provider`,
`fallback_occurred`, and `outcome` (`success`, `failed`, or `cancelled`).
`playback_provider` is `null` if no playback subprocess was created; otherwise it
identifies the provider whose native playback subprocess was started, including
cancellation during process creation. `fallback_occurred` indicates that local
fallback was invoked, even if it failed. A successful subprocess exit is not proof
that speakers were audible. No text, voice instructions, audio bytes, credentials,
file paths or backend error details are included, and fallback does not emit a
second event.

For a deliberate live regression check (existing API charges apply), run with your
configured credentials:

```sh
VOICE_RECORDING_ENABLED=true VOICE_TRANSCRIPTION_ENABLED=true \
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=openai \
VOICE_OPENAI_TTS_MODEL=gpt-4o-mini-tts VOICE_OPENAI_TTS_VOICE=cedar \
VOICE_TTS_FALLBACK_TO_MACOS=false \
uv run python -m app.main
```

Invoke `/voice`, then type `exit`, `q` and blank lines while speech is playing.
Expect one new `You >` after completion and no execution of those buffered lines.
At a real permission prompt, test a typed denial and, separately, an explicitly
intended benign approval. Repeat with Ctrl-C during recording, transcription and
playback; verify that terminal echo is restored and playback stops. Check that the
single diagnostic reports OpenAI with no fallback. Automated regression tests use
mocked audio/API operations and real pseudo-terminal queues; no billable calls were
made to develop this fix. Your previously successful live conversation test is
separate from verification of these terminal changes.

### Optional local wake phrase (`/wake`)

`/wake` starts **one** opt-in, local listening session for **Hey Jarvis**. It is
experimental keyword spotting, not speaker authentication. No listening starts
at application startup. `/voice` continues to work as before.

The detector is [PocketSphinx 5.1.1](https://pypi.org/project/pocketsphinx/5.1.1/),
using its bundled US English acoustic model and dictionary in keyphrase mode.
Both `hey` and `jarvis` are in that dictionary; no dedicated neural wake model or
separate model download is needed. We retain PocketSphinx's built-in
`kws_threshold=1e-30`, rather than inventing a threshold. Only the exact configured
phrase `Hey Jarvis` is supported. Accent, distance, noise and similar-sounding
speech can cause missed detections or false activations. The user has confirmed
successful manual operation on their MacBook; accuracy across other speakers and
environments has not been benchmarked.

Compatibility was checked locally on **Python 3.14.1, macOS arm64**: the official
5.1.1 source distribution built successfully, loaded the bundled model and phrase
vocabulary, and rejected synthetic silence. PyPI currently provides macOS wheels
for Python 3.11/3.13, not 3.14, so installation on this stack requires a native build
and Apple command-line development tools. This is not a claim of a published
Python 3.14 wheel or a guarantee for all macOS versions.

[openWakeWord](https://github.com/dscripka/openWakeWord) was also evaluated. It has
a Hey Jarvis model, but an [open upstream report](https://github.com/dscripka/openWakeWord/issues/336)
describes near-zero ONNX scores on Apple Silicon. That report was not reproduced
here. Although ONNX Runtime 1.31.1 has a Python 3.14 macOS arm64 wheel, that alone
does not verify wake accuracy. openWakeWord's pretrained models also carry
CC BY-NC-SA 4.0 restrictions. No openWakeWord dependency or model was installed.

Install the optional detector from the locked dependency metadata:

```sh
# If Apple command-line development tools are missing:
xcode-select --install
uv sync --extra wake

VOICE_WAKE_ENABLED=true VOICE_WAKE_TIMEOUT_SECONDS=30 \
VOICE_RECORDING_ENABLED=true VOICE_TRANSCRIPTION_ENABLED=true \
VOICE_TTS_ENABLED=true VOICE_TTS_PROVIDER=openai \
VOICE_OPENAI_TTS_VOICE=cedar VOICE_TTS_FALLBACK_TO_MACOS=false \
uv run --extra wake python -m app.main
```

Keep using your existing credentials; no new credential is needed. These commands
do not change `.env`. Defaults: `VOICE_WAKE_ENABLED=false`,
`VOICE_WAKE_PHRASE="Hey Jarvis"`, timeout 30 seconds (allowed range 1–120).
A missing optional package or unusable model fails before microphone access.
Existing `/voice` configuration must be enabled before wake listening can start.

At `You >`, enter `/wake`. Wait for `Listening locally — microphone active`,
then say “Hey Jarvis.” **Pause until `Recording` appears**, then
say your command and press Enter as with `/voice`. Wake capture closes before a
fresh command recording starts; words spoken during this gap are lost. A match
starts exactly one voice interaction, then returns to idle. Timeout returns to
idle without a cloud call. Ctrl-C cancels and follows the CLI's existing shutdown
behavior; it never restarts listening automatically.

Wake PCM is never written to disk, logged, stored in SQLite, or passed to STT.
The callback queue holds at most eight 64 ms mono 16 kHz/int16 frames (16 KiB),
plus bounded model/session state and the current frame. Overflow fails the session.
The session limit bounds capture and decoder history; inference and native device
operations run in a worker thread. Actual CPU/RSS has not been benchmarked. Each
activation loads a fresh detector, so initial startup may take a moment. Python
releases buffers on cleanup but does not guarantee forensic memory zeroization.

Only **after detection**, the existing voice workflow records and uploads a new
command, invokes the agent and uses configured TTS (including OpenAI Cedar).
Those existing API calls can incur charges. A false wake can therefore start
billable command capture; leave wake disabled when not deliberately testing it.
Wake detection cannot approve tools: queued keyboard input is flushed, and
sensitive tools still require a fresh typed answer at the permission prompt.
Keyboard echo is suppressed only while waiting for activation; existing `/voice`
terminal ownership resumes at handoff. The terminal limitations documented above
also apply. Cancellation waits for worker cleanup; a stuck native library call
cannot be forcibly killed safely from Python. Ctrl-C cannot undo completed actions
or API charges.

PocketSphinx's [license](https://github.com/cmusphinx/pocketsphinx/blob/v5.1.1/LICENSE)
is BSD-style with attribution/notice requirements and additional third-party
notices. The bundled acoustic model's
[README](https://github.com/cmusphinx/pocketsphinx/blob/v5.1.1/model/en-us/en-us/README)
contains Alpha Cephei's two-clause redistribution terms; preserve those notices
if redistributing dependencies/models. No model binaries are vendored here.

Manual regression checks (a successful activation uses the existing billable
voice pipeline): verify disabled `/wake` does not capture; enable it and try
silence/unrelated speech until timeout; try the phrase then wait for `Recording`
and give one benign command. Confirm one response and no automatic re-listening.
Test a typed tool denial, then Ctrl-C during listening and during playback. Verify
terminal echo returns and `/voice` can record again after restarting. Test missing
microphone permission through macOS System Settings > Privacy & Security >
Microphone for your terminal/IDE. Automated tests use mocked devices/inference and
pseudo-terminals; no microphone access or billable requests are needed.
