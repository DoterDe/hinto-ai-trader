# Hinto AI Trader

AI-assisted crypto market research and paper-trading workstation inspired by the open-source Hinto Trader project.

> **Current scope: PAPER / VIRTUAL ONLY.** Public Binance observations, deterministic analytics, offline validation and virtual portfolio simulation. No private account access, real/testnet orders or AI provider is connected.

## Run the Phase 9 dashboard

Use Python 3.11+ and Node 22.12.0 (the tested frontend runtime). From two terminals:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. On macOS/Linux, use the activated repository virtual
environment's `python` and `npm`. For initial Python setup see
[backend/README.md](backend/README.md). PowerShell users can use `npm.cmd` when
local execution policy blocks the unsigned `npm.ps1` wrapper.

The default public feed and virtual runtime are enabled. For an offline server,
set `$env:BINANCE_MARKET_DATA_ENABLED='false'` before starting the backend.
`$env:LIVE_PAPER_ENABLED='false'` disables only the paper consumer while allowing
public market observation. Environment files are not loaded automatically.
Use one backend worker. Local SQLite persistence is enabled by default at
`backend/data/paper_runtime.sqlite3` when started from `backend/`. Keep the same
working directory and settings on restart. Recovery validates the last committed
virtual session before the public source starts; missing offline bars stay missing.
Set `PAPER_PERSISTENCE_ENABLED=false` for an explicitly memory-only session.

Learn the screens in [the user guide](docs/USER_GUIDE.md), follow the
[module map](docs/MODULE_MAP.md), and review [Phase 9 evidence](docs/PHASE_9_REPORT.md).
The frontend polls read-only `/paper/snapshot` through its local `/api` proxy;
Simple/Advanced is a local display preference, never a policy change.

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
DecisionRecord`. Phase 8 consumes captured closed-bar records in a separate virtual
portfolio runtime; it never turns them into executable intents.

```text
Binance public market data
        |
        v
MarketDataHub -> FeatureEngine -> FeatureSnapshot
        -> StrategyEngine -> StrategySnapshot / StrategyCandidate
        -> DecisionEngine -> DecisionRecord (ELIGIBLE / BLOCKED / NO_ACTION)

Phase 8 closed-bar coordinator -> PaperPortfolioPolicy / bounded virtual ledger
        -> Phase 9 local atomic SQLite checkpoint -> strict restart recovery
        -> read-only telemetry -> React dashboard

Future orchestration (not connected):
DecisionRecord -> deterministic sizing -> TradeIntent
        -> RiskEngine -> ApprovedTradeIntent -> PaperExecutionGateway
        -> Position/PnL Store -> API/WebSocket -> Dashboard
```

Phase 6 also provides an offline branch: historical finalized bars replay through
the same analytical engines, then an independent evaluator measures hypothetical
signal outcomes. AI-assisted review, execution orchestration and testnet integration
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

Phase 8 adds bounded live public-close batching, generation/receipt admission,
captured production analytics, a virtual ledger, nine read-only telemetry/help
routes, and a fresh seven-page React dashboard. Late bars cannot rewrite finalized
history; missing marks remain Unknown. No upstream frontend implementation was
copied. See [frontend/README.md](frontend/README.md) for build and contract checks.

Phase 9 adds canonical, checksummed checkpoints, bounded local audit metadata,
strict configuration/continuity recovery, crash and restart validation, and
explainable persistence health. A clean shutdown preserves committed open
exposure. Storage failure stops further paper transitions; corrupt or incompatible
state never silently starts a replacement session. No strategy, cost, sizing or
execution formula changes. See [the Phase 9 report](docs/PHASE_9_REPORT.md).

For storage settings, maintenance and operating limits see the
[backend guide](backend/README.md#durable-virtual-paper-state-phase-9). All capital
and PnL remain virtual. No reset/mutation endpoint, private account connection,
real/testnet execution, AI provider or Phase 10 functionality is added.

## Upstream attribution

This project is derived conceptually and, where later copied, code-wise from **Hinto Trader** by the Hinto contributors:

- Upstream: https://github.com/meiiie/hinto-trader
- License: MIT

The original MIT notice is preserved in `LICENSE`.

## Security

Never commit API keys, secrets, seed phrases, passwords, or 2FA codes. Secrets belong only in local environment variables and must never be exposed to the frontend or logs.
