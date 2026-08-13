# JARVIS Project Status

## Current Phase

Phase 3 — Memory (core preferences done); Phase 1 fully complete

## Status

Core agent loop, tool system, security/permission layer, persistent logging,
GitHub read tools, and preference memory are working end-to-end and manually verified.

## Completed

### Phase 1 — Core
- [x] macOS + Apple Silicon environment verified
- [x] Python 3.14, uv environment
- [x] Git initialized
- [x] Configuration system (Pydantic Settings)
- [x] LLM provider abstraction (LLMProvider ABC)
- [x] OpenAI provider (Responses API, tool calling, multi-turn continuation)
- [x] Agent orchestrator (multi-step tool loop, max iteration guard)
- [x] Tool registry
- [x] Permission system (SAFE / CONFIRM / DANGEROUS) with live confirmation prompts
- [x] Command risk analyzer (shell operators, command substitution, protected paths,
      recursive-delete protection, git subcommand-level risk)
- [x] Tools: open_application, get_system_info, list_directory, read_file, terminal
- [x] Structured logging (JSON, tool_started/tool_finished, request_id, sanitized args,
      duration_ms) — writes to stdout AND logs/jarvis.log (RotatingFileHandler, 5MB/3 backups)
- [x] Ruff clean, 81/81 tests passing

### Phase 2 — Tools (partial)
- [x] GitHub read tools: list_repositories, inspect_repository
- [ ] GitHub write tools: create_commit, create_branch, list_issues, inspect_pull_request
- [ ] Browser tools (open_url, search_web)

### Phase 3 — Memory (partial)
- [x] SQLite database (conversations, projects, preferences tables)
- [x] MemoryRepository (save/get/update for conversations, projects, preferences)
- [x] remember_preference / get_preference tools
- [x] remember_project / get_project tools (same upsert pattern)
- [x] Manually verified end-to-end: remember -> recall -> update -> recall -> missing key error
      (both preferences and projects)
- [ ] Conversation memory retrieval (currently saved but not retrieved/used by agent)
- [ ] Memory retrieval strategy (avoid dumping full history into every request)

Known minor issue: agent occasionally adds unrequested framing (e.g. called a
remembered project "your favorite project" without that being stored) — likely
inferred from same-session conversation context, not from tool output. Not a
memory bug, but worth tightening the system prompt later to discourage
unsourced embellishment.

## Not Started

- [ ] Voice (Phase 4)
- [ ] Advanced agent planning / task state / retries (Phase 5)
- [ ] UI (Phase 6)
- [ ] Scheduled tasks / workflows / MCP (Phase 7)

## Current Architecture

- Python 3.14, uv
- OpenAI SDK (Responses API) — provider-agnostic via LLMProvider ABC
- Pydantic + Pydantic Settings
- SQLite (app/memory/database.py, app/memory/repository.py)
- Structured JSON logging (app/logging/logger.py)
- pytest (81 tests), pytest-asyncio, Ruff

## Next Task

Implement conversation memory retrieval: when a new user message arrives, fetch
relevant recent conversation history (not the full log) and include it in context
so the agent has continuity across turns without unbounded token growth.

## Important Rules

- Never expose API keys (sanitize_arguments redacts sensitive keys in logs).
- Never execute dangerous commands without confirmation.
- Never fake tool results.
- Never claim an operation succeeded unless it actually succeeded.
- Keep the architecture modular.
- Terminal tool: LLM never makes the final risk decision — CommandRiskAnalyzer does.
- Memory writes always go through MemoryRepository, never ad-hoc JSON/file writes.