# JARVIS TODO

## Phase 1 — Core

- [x] Configuration
- [x] LLM provider interface
- [x] OpenAI provider
- [x] Agent orchestrator
- [x] Tool registry
- [x] Safe tool system
- [x] Terminal interface (with risk analyzer)
- [x] Logging
- [x] Error handling
- [x] Tests (risk analyzer)

## Phase 2 — Tools

- [ ] Filesystem (write/delete — currently read-only: list, read)
- [x] Terminal
- [x] macOS (open_application)
- [ ] Browser
- [ ] Web
- [x] GitHub (read: list_repositories, inspect_repository)
- [ ] GitHub (write: create_commit, create_branch, list_issues, inspect_pull_request)

## Phase 3 — Memory

- [x] SQLite
- [ ] Conversation memory retrieval (saved, not yet retrieved by agent)
- [x] Long-term memory (preferences: remember_preference, get_preference)
- [ ] Project memory tools (remember_project, get_project)
- [ ] Memory retrieval strategy
- [ ] Memory management (inspect/delete/disable memory)

## Phase 4 — Voice

- [ ] Speech-to-text
- [ ] Text-to-speech
- [ ] Wake word
- [ ] Voice interruption

## Phase 5 — Advanced Agent

- [ ] Planning
- [ ] Multi-step tasks
- [ ] Task state
- [ ] Retry system
- [ ] Tool dependency handling

## Phase 6 — UI

- [ ] JARVIS dashboard
- [ ] Real-time status
- [ ] Voice interface
- [ ] Tool activity
- [ ] Memory controls

## Phase 7 — Automation

- [ ] Scheduled tasks
- [ ] Workflows
- [ ] MCP integrations
- [ ] Advanced automation
