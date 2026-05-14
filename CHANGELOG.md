# Changelog

All notable changes to Overseer are documented here. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — MVP

### Added
- Core: `Process`, `Node`, `Agent`, `Verifier`, `Function`, `Runtime`, `EventBus`.
- Quality: `Verifier` base class, `Policy` with `Retry` and `Halt`.
- Persistence: SQLite-backed event journal and snapshot store with an open JSON format.
- Adapters: `MockAdapter` (offline), `AnthropicAdapter`, `OpenAIAdapter`.
- Control plane: FastAPI server with REST + WebSocket event streaming, retry-with-override endpoint.
- UI: single-page graph view with live status, per-node drawer, intervention modal.
- CLI: `overseer run`, `overseer serve`, `overseer replay`.
- Example: `examples/research.py` — Planner/Worker/Critic demonstrating the four MVP acceptance steps.
- Tests for graph, runtime, verifier, and persistence.
