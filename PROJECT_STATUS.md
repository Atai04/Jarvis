# JARVIS Project Status

## Current Phase

Phase 1 — Core Agent

## Status

Initial project setup.

## Completed

- [x] macOS environment verified
- [x] Apple Silicon environment verified
- [x] Python 3.14 environment available
- [x] uv environment initialized
- [x] Project structure created
- [x] Git initialized
- [x] Initial dependencies installed

## Current Architecture

- Python
- OpenAI SDK
- Pydantic
- Pydantic Settings
- pytest
- Ruff

## In Progress

- [ ] Configuration system
- [ ] LLM provider abstraction
- [ ] Agent orchestrator
- [ ] Tool registry
- [ ] First safe tool
- [ ] Logging
- [ ] Basic CLI interface

## Next Task

Implement the configuration system and first LLM provider.

## Important Rules

- Never expose API keys.
- Never execute dangerous commands without confirmation.
- Never fake tool results.
- Never claim an operation succeeded unless it actually succeeded.
- Keep the architecture modular.
