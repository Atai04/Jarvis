# JARVIS Project Status

## Integration review — 2026-11-02

Status: offline regression checks completed; suitable for a deliberate developer
smoke test, not certified for unattended or security-sensitive operation. No live
paid API requests, live browser requests, GitHub operations or macOS launches were
performed in this review. Earlier status notes described manual checks; those
claims have not been revalidated here.

## Implemented and tested offline

- Async OpenAI Responses provider with existing custom function calls and
  `previous_response_id` continuations; system instructions are resent.
- Optional native `web_search` (not a separate scraping service or registry tool).
  `WEB_SEARCH_ENABLED=false` by default; context is `low`.
- `WEB_SEARCH_MAX_REQUESTS_PER_TURN=1` by default; nonnegative integers accepted,
  zero disables search. The initial request counts, continuations consume the same
  allowance, and custom functions remain available after it is exhausted.
- API-reported input/output/total token counters, with missing values represented
  as unavailable. Per-response usage logging contains counts and request IDs only.
- Source URL/title/offset metadata, preserved raw answer text, inline source URLs
  in displayed and persisted final answers. Rendering no longer appends URLs
  already present or repeats identical annotation URLs.
- Content-free search diagnostics distinguish tool availability, returned native
  search-call items and completed items. Local request/context character counts
  help investigate input size without claiming a per-component token breakdown.
- All 12 existing custom tools remain registered. Tests execute macOS/system,
  filesystem/terminal, GitHub and memory tool dispatch through the real agent with
  external calls mocked and SQLite stored in temporary directories.
- Permission routing tests cover SAFE execution, CONFIRM approval/refusal and
  DANGEROUS denial before subprocess execution. Existing command-risk tests pass.
- Hardened `open_url`: validated IPv4 connection pinning, Host/TLS preservation,
  redirect validation, no inherited proxies, time/body/redirect limits, content-type
  checks and sanitized errors. A real HTTPX/HTTPCore path is exercised down to a
  mocked TCP boundary; no real sockets or TLS handshakes are used.

## Configuration and verification

- Default model remains `gpt-5.2`; installed SDK compatibility was inspected.
- CLI startup still requires `OPENAI_API_KEY` and `GITHUB_TOKEN`; no credentials
  are included in repository examples. Do not commit `.env`.
- Validation: Ruff, pytest and `git diff --check`; see README for commands and
  optional live verification instructions. Final suite: **205 tests passing**.
- Changes remain uncommitted. No release, commit or push has been performed.

## First live-run audit

The user subsequently reported a live run. Local usage records confirm 14,621
input, 522 output and 15,143 total tokens, with no custom-tool executions logged
for that turn. Native search-call events were not previously recorded, so the
historical search occurrence and hosted-search token contribution cannot be
reconstructed from these logs. No additional live API requests were made during
the audit. See README for measured character counts and diagnostic field meanings.
The single-message wrapper was removed (54 characters); tools, memory, instructions,
the default-disabled policy and per-turn search allowance remain intact.

## Known limitations

- SDK schema compatibility and mocked requests do not verify live model/tool
  availability, account access, billing or real certificate validation.
- Search request limits are not monetary caps or per-search limits. SDK retries,
  multiple hosted searches in one response and non-search token usage can cost
  money. No price estimates or balance enforcement are implemented.
- Search is opt-in for the process/provider, not classified by user intent. Once
  enabled, any request within the allowance may search. Hosted search occurs
  before custom-tool permission checks.
- Browser access is restricted to public IPv4, standard ports and identity
  encoding. Custom routing or transparent proxies need deployment-level egress
  controls. See [browser security details](app/browser/SECURITY.md).
- Tool-argument/error logs can still expose secrets embedded in URL query strings
  or command text. Usage events themselves exclude request content. Local memory
  stores conversation text; no new retention/encryption policy was introduced.
- Permission classification is heuristic, not a complete command sandbox; broad
  home-directory file access and untrusted web content warrant further review.
- Conversations are saved, but each `run()` gets a new request ID and retrieves
  that request's records only. Cross-turn conversation-history retrieval is not
  implemented. Preferences and projects persist and are available through tools.
- No GitHub write tools, voice/UI, scheduling or advanced task/retry state.

## Recommended next milestone

Harden the permission and privacy boundary before unattended use: audit executable
arguments (not just command names), narrow sensitive-file access, redact URL/query
and command/error logging, and add adversarial tests. Then implement bounded,
consent-aware cross-turn memory retrieval with retention controls and token budgets.

## Engineering rules

- Never expose credentials or fabricate tool success.
- SAFE actions may run, CONFIRM actions require user approval, DANGEROUS actions
  are denied; the language model does not make the final permission decision.
- Keep memory writes in MemoryRepository and retain modular tool/provider APIs.
- Keep live, potentially billable smoke tests separate from the offline suite.
