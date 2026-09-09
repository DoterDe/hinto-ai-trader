# Current Codex Task — Phase 6: Deterministic Backtesting & Validation

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PHASE_4_REPORT.md`, `docs/PHASE_5_REPORT.md`, and the implemented Phase 3–5 production code completely before editing.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small reviewable batches, run targeted tests after each meaningful batch, then run the complete backend suite. Do not perform a broad repository rewrite.

The working branch is `phase-6-backtesting`. Phase 5 has been merged into `main` and the accepted baseline is **1645 backend tests passing**.

## Objective
Build an offline, deterministic **Backtesting & Validation layer** that replays historical public market observations through the existing analytical pipeline and measures what the existing StrategyEngine + DecisionEngine actually did.

The goal is validation, not optimization and not execution.

Target architecture:

```text
Historical public market observations
    -> deterministic replay clock / replay source
    -> existing MarketDataHub / FeatureEngine where practical
    -> FeatureSnapshot
    -> existing StrategyEngine
    -> StrategySnapshot / StrategyCandidate
    -> existing DecisionEngine
    -> DecisionRecord
    -> BacktestEvaluator
    -> hypothetical outcome records
    -> BacktestReport / validation metrics
```

A backtest result is a historical simulation artifact. It is not an order, approval, recommendation, profitability guarantee, or authorization for real trading.

## Non-negotiable boundaries
Do not add or use:
- Binance API keys or secrets,
- private Binance REST/WebSocket endpoints,
- balances, positions, account state or user assets,
- real order submission,
- testnet order submission,
- live-money execution,
- P2P transaction automation,
- deposits, withdrawals or transfers,
- autonomous payment flows,
- leverage or margin execution logic,
- live position sizing,
- `TradeIntent` / `ApprovedTradeIntent` generation from the backtester,
- `RiskEngine` approval as a shortcut for historical replay,
- `PaperExecutionGateway` as a path to live/testnet execution,
- AI Advisor / OpenAI API,
- ML/RL prediction models,
- automatic parameter search or optimization,
- grid search for profitable thresholds,
- genetic/Bayesian optimization,
- database/Redis unless strictly required (prefer none),
- frontend redesign,
- reconstructed full order book,
- performance/profitability claims.

Phase 6 must remain completely offline and deterministic in tests.

## Critical anti-overfitting rule
Do **not** tune StrategyEngine or DecisionEngine thresholds against historical returns in Phase 6.

The existing Phase 4 and Phase 5 settings are inputs to validation, not parameters to optimize.

If multiple policies/settings are compared in tests or examples, they must be explicitly supplied fixed configurations for engineering verification only. Do not add an optimizer or choose a “best” configuration based on return.

## Baseline first
Before editing:
1. confirm `git branch --show-current` is `phase-6-backtesting`;
2. confirm `git status`;
3. run the complete backend suite and confirm the accepted baseline of **1645 passing tests**;
4. inspect at minimum:
   - `backend/src/domain/market_data.py`
   - `backend/src/application/market_data_hub.py`
   - `backend/src/application/feature_engine.py`
   - `backend/src/domain/features.py`
   - `backend/src/application/strategy_engine.py`
   - `backend/src/domain/strategies.py`
   - `backend/src/application/decision_engine.py`
   - `backend/src/domain/decisions.py`
   - existing replay/offline test fixtures and source abstractions
   - Phase 3–5 tests
   - `docs/ARCHITECTURE.md`
   - `docs/PHASE_4_REPORT.md`
   - `docs/PHASE_5_REPORT.md`.

Do not redesign Phase 1–5 unless a minimal compatibility change is clearly required and independently tested.

## Core design principles
1. **No look-ahead bias.** A decision may use only information available at or before its source observation.
2. **Next-observation execution convention.** Historical evaluation must not assume a fill at the same closing price that produced the signal unless that behavior is explicitly justified. Prefer entry at the next bar/open observation.
3. **Deterministic replay clock.** Historical timestamps, not wall-clock time, drive freshness and evaluation.
4. **Reuse production analytical code.** Do not create a separate “backtest strategy” implementation with different formulas.
5. **Separate market replay from outcome evaluation.** Replayed market data creates decisions; future bars are used only afterward to evaluate outcomes.
6. **No optimization.** Measure existing rules; do not fit them.
7. **Explicit transaction-cost assumptions.** Fees/slippage are configurable simulation assumptions, never hidden.
8. **Stable identities and deduplication.** Equivalent analytical observations must not be counted repeatedly.
9. **Bounded memory.** Support streaming/incremental evaluation rather than loading unlimited histories into mutable structures when practical.
10. **Deterministic offline tests.** No exchange/network dependency.
11. **Transparent limitations.** Metrics must state exactly what they measure.
12. **No profitability claims.** Historical simulation does not imply future performance.

## Scope: Phase 6 validates signals, not a real portfolio
Do not build a live portfolio/risk/position-management system in this phase.

Prefer a **normalized hypothetical signal outcome model**:
- each accepted historical decision can produce one hypothetical outcome,
- no real quantity is required,
- no leverage is used,
- no account balance is required,
- returns are expressed as dimensionless percentages/Decimal fractions,
- transaction costs are expressed in basis points or fractional return,
- metrics describe the historical signal-return sequence.

If an equity-like curve is provided, name and document it honestly as a normalized hypothetical curve. Do not imply that it models liquidation, margin, exchange funding, taxes, or an actual user account.

## Historical data contract
Create immutable typed historical-input contracts suitable for offline replay.

Prefer a minimal normalized OHLCV bar contract close to:

```text
HistoricalBar
- symbol
- interval
- open_time
- close_time
- open
- high
- low
- close
- volume
- quote_volume if required by existing feature semantics
- taker_buy_base_volume / other already-required public kline fields if needed
- closed = true
```

Use `Decimal` for prices/volumes where consistent with the existing market-data domain.

Validation must reject:
- naive timestamps,
- non-finite values,
- nonpositive prices,
- high < low,
- OHLC outside high/low,
- negative volume,
- non-increasing bar time,
- duplicate bars for the same symbol/time,
- overlapping/misaligned intervals where the replay contract forbids them.

Do not fabricate missing bars.

If the existing normalized kline event model already provides everything needed, reuse it instead of creating redundant types.

## Historical input loader
Add a small offline loader only if useful.

Preferred supported source for Phase 6:
- deterministic in-memory typed bars for tests;
- optionally a local CSV/NDJSON loader for public historical bars.

Requirements for a file loader:
- local files only;
- no automatic network download;
- strict schema validation;
- deterministic ordering;
- clear duplicate/gap behavior;
- streaming iterator where practical;
- no secret/account fields.

Do not add a Binance historical downloader in this phase.

## Replay engine
Implement a deterministic replay mechanism that feeds historical observations in chronological order.

Reuse existing production components wherever practical. The ideal path is:

```text
HistoricalBar/Event
    -> MarketDataHub
    -> FeatureEngine
    -> StrategyEngine
    -> DecisionEngine
```

However, inspect the existing asynchronous architecture first. Do not force a fragile async polling design just to reuse a class.

The replay mechanism must:
- preserve per-symbol chronological ordering;
- define deterministic ordering for equal timestamps across symbols;
- advance a simulated/replay clock explicitly;
- allow FeatureEngine to fully consume an event before reading the resulting snapshot;
- never use `datetime.now()` for replay correctness;
- never sleep based on historical wall-clock gaps;
- not create synthetic missing candles;
- preserve Phase 3 reconnect/gap semantics where relevant;
- be offline and finite.

For multi-symbol replay, define and document ordering. Prefer `(event_time, symbol, stable input index)` or another explicit deterministic order.

## Freshness under historical replay
Phase 4 and 5 intentionally reject old wall-clock snapshots. The backtester must not disable these safety rules globally.

Instead, pass the historical replay time explicitly so that:
- a historical snapshot is fresh relative to the simulated clock at that moment;
- production `latest()` behavior remains unchanged;
- no production maximum-age default is weakened for backtesting;
- tests can prove the same snapshot is stale under real later time but valid at its historical evaluation time.

Do not patch production code to “ignore freshness in backtest mode.”

## Decision sampling / deduplication
Only count stable analytical observations once.

At minimum:
- use `decision_id`, `observation_id`, or an equally stable upstream identity;
- repeated reads of the same observation must not create multiple hypothetical entries;
- NO_ACTION and BLOCKED outcomes are counted for diagnostics but never become hypothetical trades/outcomes;
- only `DecisionOutcome.ELIGIBLE` may enter the hypothetical outcome evaluator;
- a changed outcome/observation may be a new evaluation event.

Keep dedupe state bounded when feasible. For a finite backtest, a run-local set of already-counted decision IDs is acceptable; document memory behavior.

## Entry convention — anti-look-ahead
Use a conservative deterministic convention.

Default Phase 6 convention:
- Decision is produced from closed bar **t**.
- Hypothetical entry uses the **next bar t+1 open**.
- If no next bar exists, no completed outcome is created and the reason is recorded.

Never fill at bar `t` close when that same close contributed to the decision unless a separate test mode explicitly demonstrates why it is non-look-ahead. Do not make such same-bar mode the default.

## Exit convention
Keep Phase 6 simple and auditable.

Use a configurable fixed holding horizon in complete bars, for example:

```text
holding_period_bars = 5
```

Define exact semantics in code/docs. Prefer:
- entry = open of bar t+1;
- exit = close of bar t+holding_period_bars;
- all required bars must exist and be chronologically valid.

If the chosen indexing differs after inspecting existing interval semantics, document it with concrete examples and test exact boundaries.

Do not add stop-loss, take-profit, trailing stops, liquidation, leverage, or dynamic exit optimization in Phase 6.

## Overlapping signal policy
Choose one explicit deterministic policy and document it.

Preferred default for Phase 6 validation:
- each unique eligible decision is evaluated independently as a **signal outcome** even if horizons overlap;
- metrics must clearly be called signal-level metrics, not portfolio-capital metrics.

This is preferable for strategy validation because it measures every eligible decision without inventing portfolio sizing.

If you instead enforce one active hypothetical position per symbol, document why and record skipped signals explicitly. Do not silently drop overlapping signals.

Do not mix both interpretations in one metric without labeling them.

## Transaction-cost model
Add deterministic simulation settings with conservative, explicit defaults.

Prefer settings close to:

```text
BACKTEST_HOLDING_PERIOD_BARS=5
BACKTEST_FEE_BPS_PER_SIDE=5
BACKTEST_SLIPPAGE_BPS_PER_SIDE=2
```

These are engineering assumptions only, not claims about current exchange fees or actual achievable fills.

For LONG:
- adverse entry slippage raises effective entry price;
- adverse exit slippage lowers effective exit price.

For SHORT:
- adverse entry slippage lowers effective sale/entry price;
- adverse exit slippage raises effective buyback/exit price.

Apply the configured fee on each side consistently.

Store both:
- gross return before costs,
- total simulated cost,
- net return after costs.

Validate all cost settings as finite and nonnegative. Do not permit a hidden negative fee/rebate unless explicitly modeled in a future phase.

## Hypothetical outcome domain
Create immutable typed models close to:

```text
BacktestOutcomeStatus = COMPLETED | INCOMPLETE

BacktestSignalOutcome
- outcome_id
- decision_id
- observation_id
- symbol
- direction
- decision_time
- entry_time
- exit_time
- entry_price_raw
- exit_price_raw
- effective_entry_price
- effective_exit_price
- holding_period_bars
- gross_return
- simulated_cost_return
- net_return
- favorable_excursion (optional if exact semantics are implemented)
- adverse_excursion (optional if exact semantics are implemented)
- status / reason
```

Do not include a real-money quantity, account balance, leverage, exchange order ID or execution credential.

`outcome_id` must be deterministic from stable inputs and backtest settings.

Incomplete outcomes must be explicit rather than fabricated.

## MFE / MAE (optional but preferred)
If implemented, calculate maximum favorable excursion and maximum adverse excursion only from bars **after entry** and through the exit horizon.

For LONG and SHORT, define signs consistently and test them independently.

Do not use post-exit bars.

If exact MFE/MAE semantics would make the batch too large, defer them rather than implement ambiguous formulas.

## Validation metrics
Implement pure deterministic metric functions over completed hypothetical outcomes.

Required metrics:
- total input bars/events;
- evaluated decision count;
- ELIGIBLE count;
- BLOCKED count;
- NO_ACTION count;
- unique completed signal outcomes;
- incomplete outcome count;
- LONG/SHORT counts;
- win count / loss count / flat count;
- win rate among completed non-flat outcomes (document denominator);
- mean gross return;
- mean net return / expectancy per completed signal;
- median net return if implemented cleanly;
- sum of gross returns;
- sum of simulated costs;
- sum of net returns;
- gross profit;
- gross loss absolute magnitude;
- profit factor (`gross_profit / abs(gross_loss)`) with explicit zero-loss semantics;
- best / worst net outcome;
- consecutive win/loss streaks;
- normalized cumulative-return curve;
- maximum drawdown of that explicitly defined normalized signal-return curve.

Do not label additive signal-return drawdown as “account drawdown” unless a true portfolio model exists.

If you implement a compounded curve, define behavior for returns <= -100% and do not silently clamp impossible values.

## Regime and cohort breakdowns
Use existing Phase 3/4 analytical context where available to produce deterministic cohort summaries.

At minimum consider breakdowns by:
- symbol;
- LONG vs SHORT;
- Strategy/Decision outcome;
- incomplete vs complete strategy coverage;
- simple existing regime labels/inputs if the repository already exposes a stable regime category.

Do not invent opaque clustering.

If Phase 3 exposes only numeric regime inputs and no stable category label, either:
- report those inputs separately, or
- define a very small documented deterministic bucketing helper solely for reporting.

Do not change strategy decisions based on these post-hoc breakdowns.

## Time-segment / walk-forward reporting
Add chronological segmentation for validation without optimization.

Preferred capability:
- split a completed backtest chronologically into N fixed segments or explicit date ranges;
- compute the same metrics independently per segment;
- preserve settings unchanged across all segments.

This is a **walk-forward report**, not walk-forward optimization.

Do not train/tune on an earlier segment and automatically alter strategy parameters for later segments.

Tests must ensure no segment sees future outcomes from another segment.

## Backtest run/report contracts
Create immutable typed run-level output close to:

```text
BacktestRunMetadata
- run_id
- engine_version
- started_from / ended_at historical timestamps
- symbols
- interval
- input_count
- strategy_settings_id
- decision_policy_id
- backtest_settings_id

BacktestMetrics
BacktestCohortMetrics
BacktestRunReport
- metadata
- counts
- metrics
- per_symbol
- per_direction
- chronological_segments
- warnings/limitations
```

All IDs should be deterministic from dataset identity + relevant settings where practical.

Do not use random UUIDs for analytical reproducibility.

## Dataset identity
Create a stable run/dataset identity without loading arbitrary secret material into hashes.

For in-memory test data, derive identity from canonical normalized historical records and schema/version.

For local file inputs, prefer hashing normalized parsed records or file bytes plus parser version. Document the choice.

Same historical data + same analytical settings + same backtest settings must yield the same run ID and same outputs.

Changed data/settings must change the corresponding identity.

## Suggested structure
Prefer something close to:

```text
backend/src/
  domain/
    backtesting.py
  application/
    backtest_engine.py
    backtest_settings.py
    backtest_metrics.py
    historical_replay.py
  infrastructure/
    historical_files.py          # only if a local loader is added
```

Small helpers for deterministic identity or outcome calculations are acceptable.

Avoid a large framework.

## API boundary
Phase 6 does **not** require a public HTTP endpoint.

Prefer the backtester as an offline Python/application service first.

If an API is added, it must be read-only over already-computed in-memory results and must not accept paths that allow arbitrary server filesystem access.

Do not add an endpoint that triggers a long-running historical backtest from arbitrary user input in this phase.

Do not add network download endpoints.

## Performance and resource behavior
Phase 6 should work for moderately large offline datasets without obviously unbounded duplicate copies.

Requirements:
- streaming/iterator input where practical;
- bounded feature history remains owned by existing FeatureEngine;
- do not retain every raw event twice;
- retain completed outcome records only when needed for final metrics/reporting;
- document complexity and memory trade-offs;
- tests should include at least one longer deterministic replay to catch accidental quadratic behavior.

Do not perform premature micro-optimization.

## Error handling
Fail closed and explicitly for:
- malformed historical bars,
- duplicate/unsorted bars where ordering cannot be resolved safely,
- interval mismatch,
- missing required next-entry bar,
- missing exit horizon,
- nonfinite arithmetic,
- invalid transaction-cost settings,
- invalid direction,
- malformed DecisionRecord/StrategySnapshot,
- duplicated analytical decision identity,
- impossible timestamp ordering.

A missing future bar at dataset end is normally an **INCOMPLETE** signal outcome, not a fabricated fill.

## Testing requirements
Add comprehensive deterministic offline tests.

### Historical domain / loader
Test:
- immutable records;
- timestamp awareness;
- OHLC consistency;
- finite numeric validation;
- volume bounds;
- duplicate handling;
- deterministic ordering;
- file schema validation if loader exists;
- no network access.

### Replay / anti-look-ahead
Test at minimum:
- chronological replay;
- same historical data -> same feature/strategy/decision sequence;
- simulated historical clock keeps historical snapshots valid at historical time;
- later real clock would make the same snapshot stale;
- decision from bar t never receives bar t+1 data before it is created;
- entry uses bar t+1 open;
- changing only future bars cannot change the decision at t;
- missing next bar -> incomplete outcome;
- missing exit bar -> incomplete outcome;
- no synthetic bars are inserted;
- multi-symbol equal-timestamp ordering is deterministic.

### Decision filtering / dedupe
Test:
- ELIGIBLE -> possible hypothetical outcome;
- BLOCKED -> diagnostic count only;
- NO_ACTION -> diagnostic count only;
- repeated same decision ID counted once;
- changed observation creates new eligible evaluation;
- no TradeIntent/RiskEngine/ExecutionGateway calls.

### Outcome math
Test exact LONG and SHORT formulas independently:
- zero fees/slippage;
- fee only;
- slippage only;
- combined costs;
- flat market;
- positive move;
- adverse move;
- Decimal precision;
- exact horizon boundary;
- invalid/nonfinite settings;
- deterministic outcome ID.

Do not compute expected returns by calling the production helper under test.

### Metrics
Test:
- empty completed set;
- one winner;
- one loser;
- all wins;
- all losses;
- mixed flat/win/loss;
- profit-factor zero-loss semantics;
- mean/median if implemented;
- cumulative normalized return;
- maximum drawdown exact cases;
- best/worst;
- streak calculations;
- LONG/SHORT split;
- symbol split;
- chronological segment split;
- counts reconcile exactly with raw records.

### Integration
Build a deterministic small historical dataset that flows through the actual implemented production analytical pipeline where practical:

```text
historical bars
-> feature generation
-> strategy evaluation
-> decision evaluation
-> backtest outcome
-> metrics
```

Verify:
- Phase 3 warm-up behavior is preserved;
- early bars do not magically produce warmed indicators;
- Phase 4 candidate rules are unchanged;
- Phase 5 eligibility rules are unchanged;
- repeated runs are byte/serialization deterministic where intended;
- no wall-clock/network dependency exists.

### Regression / scope
Explicitly verify:
- no API keys/secrets;
- no account endpoints;
- no order submission;
- no live/testnet execution;
- no P2P automation;
- no AI provider;
- no ML/RL optimizer;
- no parameter optimization;
- no production strategy threshold modification based on returns.

All Phase 1–5 tests must remain passing.

## Documentation
Update:
- `CODEX_TASK.md`,
- `docs/ARCHITECTURE.md`,
- `backend/README.md`,
- root README only if useful.

Create `docs/PHASE_6_REPORT.md` at completion.

Document exactly:
- historical input schema;
- replay ordering;
- simulated clock behavior;
- anti-look-ahead guarantees;
- decision deduplication;
- entry convention;
- exit horizon convention;
- transaction-cost formulas;
- LONG/SHORT return formulas;
- outcome status semantics;
- metric formulas and denominators;
- profit-factor edge cases;
- normalized drawdown definition;
- cohort/regime reporting;
- chronological segment reporting;
- deterministic identity rules;
- performance/memory characteristics;
- limitations and missing market microstructure;
- why this is validation rather than optimization;
- why historical results do not imply future returns.

## Development batches

### Batch 1 — historical contracts + settings + pure outcome math
- typed historical bars / normalized input reuse;
- BacktestSettings;
- BacktestSignalOutcome contracts;
- deterministic identities;
- pure LONG/SHORT cost/return calculation;
- targeted tests.

### Batch 2 — deterministic replay + decision capture
- replay clock/source;
- chronological ordering;
- production Feature/Strategy/Decision integration where practical;
- stable decision capture/deduplication;
- anti-look-ahead tests;
- targeted tests.

### Batch 3 — horizon/outcome evaluator
- next-bar entry;
- fixed-bar exit horizon;
- incomplete outcomes;
- fee/slippage handling;
- optional MFE/MAE if precise;
- targeted tests.

### Batch 4 — metrics + cohort/segment reporting
- aggregate counts;
- win/loss/flat;
- expectancy;
- profit factor;
- cumulative normalized returns;
- normalized maximum drawdown;
- streaks;
- symbol/direction breakdown;
- chronological segment reporting;
- targeted tests.

### Batch 5 — full integration, longer replay, documentation
- deterministic end-to-end historical fixture;
- Phase 1–5 regression verification;
- performance sanity check;
- docs/report;
- full suite.

After each batch, run targeted tests and fix failures before proceeding.

## Completion commands
At minimum from `backend` run:

```bash
python -m pytest
python -m pip check
```

Also run:
- import/OpenAPI check to ensure existing API remains stable;
- offline lifespan smoke test;
- deterministic replay twice and compare report identity/output;
- `git diff --check`;
- `git status`;
- `git diff --stat`.

Do not commit or push automatically.

## Acceptance criteria
Phase 6 is complete only when:
1. Existing production FeatureEngine, StrategyEngine and DecisionEngine semantics are preserved.
2. Historical replay is deterministic and offline.
3. Historical freshness uses an explicit simulated clock, not disabled safety checks.
4. No look-ahead path exists in the tested default flow.
5. Default hypothetical entry is after the decision-producing bar, preferably next-bar open.
6. Exit horizon is fixed, explicit and deterministic.
7. Fees/slippage assumptions are explicit, validated and included in net returns.
8. BLOCKED/NO_ACTION never become hypothetical trades/outcomes.
9. Duplicate reads of one analytical observation are not double-counted.
10. Missing future data produces INCOMPLETE, not fabricated outcomes.
11. Core metrics are independently tested.
12. Cohort/time-segment reports do not change decisions or settings.
13. No parameter optimizer is introduced.
14. No TradeIntent, RiskEngine approval, or execution is triggered by Phase 6.
15. No private/account/API-key/P2P integration exists.
16. All 1645 baseline tests remain passing.
17. New Phase 6 tests pass.
18. Documentation precisely states limitations and no-profitability guarantee.

## Completion report
At the end report:
- exact baseline result;
- files created;
- files modified;
- historical data contract;
- replay architecture;
- simulated clock design;
- anti-look-ahead mechanism;
- entry/exit conventions;
- transaction-cost defaults and formulas;
- outcome-domain contracts;
- deduplication behavior;
- exact metric definitions;
- cohort/segment reporting;
- deterministic identities;
- exact targeted batch results;
- exact complete `python -m pytest` result;
- warnings;
- dependency/import/OpenAPI/lifecycle results;
- deterministic repeated-run check;
- intentionally deferred work;
- remaining technical risks;
- final `git status` and `git diff --stat`.

Do not commit or push until reviewed.
