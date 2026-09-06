# AGENTS.md

## Mission
Build a modular AI-assisted crypto market research and paper-trading workstation derived from the Hinto Trader architecture.

## Codex model profile
The primary coding agent for this repository is **GPT-6 Astra in Codex**.

Optimize work for Astra as follows:
1. Read this file and `CODEX_TASK.md` before changing code.
2. Inspect the relevant existing files before editing; do not infer structure from filenames alone.
3. Work in small, reviewable phases with explicit acceptance criteria.
4. Prefer targeted edits over broad rewrites.
5. After each meaningful batch, run the narrowest relevant tests first, then the full backend test suite before completion.
6. Do not silently change architecture, dependencies, public interfaces, or task scope. Record any necessary deviation in the completion report.
7. When an external API contract is uncertain or version-sensitive, verify it against the current official documentation before coding rather than guessing.
8. Keep responses concise but include: files changed, commands/tests run, results, architectural decisions, and remaining risks.
9. Do not spend effort redesigning already-working code unless the current task requires it.
10. Preserve context across phases by updating documentation when interfaces or architecture change.

## Non-negotiable rules
1. Default execution mode is `paper`.
2. Do not implement autonomous real-money order execution.
3. AI output is advisory only and cannot bypass deterministic risk rules.
4. Secrets must never appear in source code, frontend bundles, logs, tests, fixtures, or documentation.
5. Keep exchange-specific code behind interfaces/adapters.
6. Preserve upstream MIT attribution when copying substantial Hinto code.
7. Prefer small, testable services over large orchestration classes.
8. Any network integration must have timeouts, reconnect handling, and stale-data detection.
9. Every signal must have a unique ID and timestamp.
10. Every execution decision must be auditable.

## Target flow

```text
MarketData
-> FeatureEngine
-> Strategy
-> SignalCandidate
-> AIAdvisor
-> DecisionEngine
-> RiskEngine
-> ApprovedTradeIntent
-> ExecutionGateway (Paper/Testnet)
-> PositionStore
-> API/WebSocket
-> UI
```

## Backend conventions
- Python 3.11+
- FastAPI
- Pydantic models
- pytest
- type hints everywhere practical
- domain layer must not import FastAPI or exchange SDKs

## Frontend conventions
- React + TypeScript
- presentation code must not contain secrets
- mode, connectivity, risk state, and data freshness must be visible

## Definition of done for each task
- implementation complete
- tests added/updated
- existing tests pass
- no secrets added
- documentation updated when architecture changes
- summary of changed files and remaining risks
