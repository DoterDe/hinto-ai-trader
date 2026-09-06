# AGENTS.md

## Mission
Build a modular AI-assisted crypto market research and paper-trading workstation derived from the Hinto Trader architecture.

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
