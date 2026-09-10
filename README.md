# Hinto AI Trader

AI-assisted crypto market research and paper-trading workstation inspired by the open-source Hinto Trader project.

> **Safety scope:** this repository is intentionally paper/testnet-first. Autonomous real-money order execution is not implemented. Public Binance market data, backtesting, paper execution, deterministic risk controls, and AI-assisted signal review are the supported scope.

## Goals

- Consume live Binance market data for multiple symbols.
- Build a reusable feature engine (trend, momentum, volatility, volume, top-of-book context).
- Keep strategy logic independent from execution.
- Add an AI Advisor that can approve/reject/flag a candidate signal, but can never bypass deterministic risk controls.
- Support backtesting and paper trading with realistic commissions/slippage assumptions.
- Expose the system through FastAPI and a React/Tauri-style dashboard.
- Preserve a clean path for research, auditing, and reproducible tests.

## Architecture

The target below includes future orchestration. The implemented observation and
analysis boundary is `MarketDataHub -> FeatureEngine -> FeatureSnapshot ->
StrategyEngine -> StrategySnapshot / StrategyCandidate -> DecisionEngine ->
DecisionRecord`; it ends at analytical eligibility.

```text
Binance public market data
        |
        v
MarketDataHub -> FeatureEngine -> FeatureSnapshot
        -> StrategyEngine -> StrategySnapshot / StrategyCandidate
        -> DecisionEngine -> DecisionRecord (ELIGIBLE / BLOCKED / NO_ACTION)

Future orchestration (not connected):
DecisionRecord -> deterministic sizing -> TradeIntent
        -> RiskEngine -> ApprovedTradeIntent -> PaperExecutionGateway
        -> Position/PnL Store -> API/WebSocket -> Dashboard
```

Phase 6 also provides an offline branch: historical finalized bars replay through
the same analytical engines, then an independent evaluator measures hypothetical
signal outcomes. AI-assisted review, production portfolio orchestration and testnet integration
remain future work. AI cannot bypass deterministic risk controls.

## Project status

Phase 1 backend is implemented: immutable domain models, deterministic risk
checks and decision history, idempotent in-memory paper fills, and health/config
endpoints. See `backend/README.md` for setup and operating limits, `CODEX_TASK.md`
for scope, and `docs/ARCHITECTURE.md` for the staged architecture.

Phase 2 adds public Binance USD-M Futures data for eight symbols, normalized
events, connection/freshness tracking, bounded subscriptions, and read-only
market-data endpoints. Depth is exposed as deltas; no local order book is built.

Phase 3 adds deterministic numerical feature snapshots, bounded closed-candle
history, per-group freshness/warmup, and read-only `/features/status` and
`/features/{symbol}/latest` endpoints. Features remain independent of strategies,
AI, and execution. See `docs/PHASE_3_REPORT.md` for formulas, validation, and limits.

Phase 4 adds on-demand trend-following, momentum/continuation and mean-reversion
assessments with explicit evidence, bounded scores/confidence, weighted consensus,
and deterministic analytical candidate IDs. `GET /strategies/status` and
`GET /strategies/{symbol}/latest` are read-only. Candidates have no quantity,
leverage or order type and do not reach the paper gateway. These engineering
defaults have no profitability claim. See [the Phase 4 report](docs/PHASE_4_REPORT.md).

Phase 5 adds an on-demand DecisionEngine with explicit freshness, candidate
identity, agreement and contributor gates. Read-only `GET /decisions/status` and
`GET /decisions/{symbol}/latest` expose immutable eligibility records and stable
reason codes. `ELIGIBLE` is analytical eligibility, with no sizing, intent creation,
risk approval or execution. No task, subscription or dependency is added.
See [the Phase 5 report](docs/PHASE_5_REPORT.md) for policy defaults and validation.

Phase 6 adds deterministic offline signal validation, next-bar-open entry,
fixed-horizon outcomes, explicit fee/slippage assumptions and reproducible
metrics/cohort/time-segment reports. Historical replay preserves production
warm-up and freshness checks using simulated time. It creates no intent, quantity,
account or execution path and performs no parameter optimization. Historical
signal-return curves are not account performance or a profitability guarantee.
See [the Phase 6 report](docs/PHASE_6_REPORT.md) and the backend usage guide.

Phase 7 adds offline shared-capital simulation with virtual notional reservations,
deterministic simultaneous arbitration, fixed-horizon positions and marked-equity
exposure/drawdown gates. Unknown holding marks block new reservations and remain
explicitly incomplete. This separate PaperPortfolioPolicy does not call Phase 1
risk/execution services or create executable intents. See
[the Phase 7 report](docs/PHASE_7_REPORT.md) for formulas, tests and limitations.

## Upstream attribution

This project is derived conceptually and, where later copied, code-wise from **Hinto Trader** by the Hinto contributors:

- Upstream: https://github.com/meiiie/hinto-trader
- License: MIT

The original MIT notice is preserved in `LICENSE`.

## Security

Never commit API keys, secrets, seed phrases, passwords, or 2FA codes. Secrets belong only in local environment variables and must never be exposed to the frontend or logs.
