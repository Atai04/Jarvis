# JARVIS Architecture

## High-Level Architecture

User
↓
Interface
↓
Agent Orchestrator
↓
LLM Provider
↓
Tool Selection
↓
Tool Registry
↓
Tool Execution
↓
Observation
↓
Agent
↓
Response

## Core Components

### Agent

Responsible for:

- Understanding user requests
- Managing execution
- Selecting tools
- Processing tool results
- Returning final responses

### LLM

Provider abstraction.

Potential providers:

- OpenAI
- Anthropic
- Gemini

The agent must not depend directly on one provider.

### Tools

All external actions are implemented as explicit tools.

Examples:

- filesystem
- terminal
- browser
- macOS
- GitHub
- web

### Memory

Initially SQLite.

Memory should be retrieved when relevant rather than injecting the entire history into every request.

### Security

Every tool has a permission level.

Possible levels:

- SAFE
- CONFIRM
- DANGEROUS

### Voice

Voice is intentionally not part of Phase 1.

It will be added after the core agent is stable.
