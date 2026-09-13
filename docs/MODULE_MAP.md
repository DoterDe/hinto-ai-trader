# Phase 8 module map

Every module in this path handles public information or virtual state. **None can
move money.** The table explains the input, work and output without requiring a
reader to understand Python. Source links are provided for deeper inspection.

```text
Public Binance adapters -> MarketDataHub
                              |
                         closed-bar observer
                              |
                         LiveBarBatcher
                              |
                 real age / connection admission
                              |
               LivePaperAnalysis: isolated closed view
                   FeatureEngine -> StrategyEngine -> DecisionEngine
                              |
                    LivePaperCoordinator
                              |
                  PaperPortfolioPolicy -> bounded live ledger
                              |
                 telemetry -> GET API -> React dashboard
```

The ordinary public Hub and existing on-demand analytical API remain available.
The isolated closed view prevents a newer observation in that ordinary cache from
changing a decision for an earlier closed candle. These are the same production
engine classes with separate state, not duplicated strategy formulas.

| Module / source | What goes in | What it does | What comes out | What it cannot do |
| --- | --- | --- | --- | --- |
| [MarketDataHub](../backend/src/application/market_data_hub.py) | Normalized public events and connection status | Caches public observations, reports freshness, distributes bounded queues; a separate observer tags closed candles with connection identity/generation | Current public snapshots and tagged closed observations | Read an exchange account, fill gaps, reconstruct a complete order book, or place orders |
| [LiveBarBatcher](../backend/src/application/live_bar_batcher.py) | Closed observations, configured symbols, UTC and monotonic clocks | Collects equal-close groups until complete or timeout; sorts symbols and diagnoses duplicate/conflicting/late bars | Finalized groups with explicit missing/conflicting members | Invent missing bars, reopen finalized history, predict which missing earlier group will arrive |
| [LivePaperAnalysis](../backend/src/application/live_paper_analysis.py) | Only real-age/generation-admitted closed groups | Advances a canonical close-time clock and feeds an isolated instance of the existing analytical pipeline | Feature, strategy and decision records for exactly that close | Read newer ordinary-cache evidence, bypass admission, manufacture optional book context |
| [FeatureEngine](../backend/src/application/feature_engine.py) and [FeatureHistory](../backend/src/application/feature_history.py) | Public observations, bounded continuous candle history and source metadata | Calculate typed indicators with warm-up, continuity and numerical checks | FeatureSnapshot with ready/stale/warming/unavailable groups | Decide to trade, infer missing candles or repair a disconnected history |
| [StrategyEngine](../backend/src/application/strategy_engine.py) | Typed feature snapshot and explicit time | Applies fixed trend, momentum and mean-reversion formulas; combines their evidence | Assessments, composite score, confidence, agreement and optional candidate | Treat confidence as a profit probability, fit thresholds to returns or execute |
| [DecisionEngine](../backend/src/application/decision_engine.py) | Strategy snapshot/candidate and explicit time | Checks readiness, freshness, identity and configured decision policy | Inert ELIGIBLE, BLOCKED or NO_ACTION record with reasons and stable ID | Create a quantity-bearing intent, approve real risk or call a gateway |
| [LivePaperCoordinator](../backend/src/application/live_paper_coordinator.py) | Tagged closed queue, clocks, settings and grouped evidence | Checks real ages and generations, orders analytical/virtual work, diagnoses loss and manages cleanup | Runtime health, captured analyses and bounded events | Read private APIs, turn API GETs into processing triggers, allow future bars into an older decision |
| [PaperPortfolioPolicy](../backend/src/application/paper_portfolio_policy.py) | Existing DecisionRecords and current known virtual state | Ranks simultaneous candidates deterministically and applies fixed size/capacity/drawdown gates | RESERVED / REJECTED / IGNORED decisions | Optimize against future returns, size by confidence, borrow, pyramid, reverse or invoke Phase 1 RiskEngine |
| [LivePaperPortfolio](../backend/src/application/live_paper_portfolio.py) | Admitted groups and policy results | Applies exact next-open entries, fixed-horizon marks/exits and Phase 6/7 cost math; bounds recent history | Virtual reservations/positions/closes, equity, exposure and curve | Access exchange balances, fabricate a missing mark, force an unobserved close, call PaperExecutionGateway |
| [PaperPortfolioLedger](../backend/src/application/paper_portfolio_ledger.py), offline Phase 7 | Finite historical replay frames | Records the finite run's full virtual audit for independent reporting | Deterministic PaperPortfolioReport | Serve as an indefinitely growing live history; it is not the Phase 8 continuous storage |
| [Telemetry projection](../backend/src/application/live_paper_telemetry.py) | Existing coordinator, Hub and virtual state | Copies a coherent read-only view with times, reasons and configuration identities | JSON-safe status/portfolio/market/analysis/history snapshots | Evaluate a new strategy, reserve capacity, advance clocks or replace unknown equity with zero |
| [FastAPI telemetry routes](../backend/src/api/live_paper.py) | GET requests with optional bounded limits | Returns typed projections or safe validation/unavailable responses | Nine read-only telemetry/help resources | Accept commands, credentials or financial mutation requests |
| [Dashboard contract exporter](../backend/scripts/export_dashboard_contract.py) | Backend serialization models and [explanation catalog](../backend/src/application/explanations.py) | Generates the browser schema and shared help; verifies deterministic output | JSON schema/catalog, then generated TypeScript via frontend script | Start a feed, connect to an exchange, make decisions or allow nonfinite Decimal strings |
| [React frontend](../frontend/src/App.tsx) | Validated GET snapshots and local display preference | Presents seven pages, safe formatting, explanations and chart coordinates | Human-readable observations and virtual state | Compute authoritative indicators/decisions/approvals, change backend settings, move money |

The clock is explicit: real UTC gates freshness; a monotonic timer gates batch
waiting; canonical close time governs admitted analytical evaluation. Raw
publication/receipt times and source generations remain visible in telemetry.

The coordinator starts once per application lifespan. The public source starts
after consumers register. Shutdown cancels and awaits source, coordinator and
feature consumers, removes subscriptions and resolves timers. No persistence is
provided: restart starts a new virtual session.

Phase 6 HistoricalReplay, BacktestEvaluator and Phase 7 PaperPortfolioEngine remain
offline validation services. The dashboard's Backtest page explains them; it does
not add a remote execution or report-upload workflow.

Future execution requires separately reviewed deterministic intent/sizing,
independent pre-execution risk review, an execution port and an exchange adapter.
Future P2P public observations would feed separate analytics/quote comparison and
user-visible information. Neither future boundary is operational in Phase 8.
