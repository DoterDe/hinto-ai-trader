# Current Codex Task — Phase 7: Deterministic Paper Portfolio & Risk Simulation

## Implementation status

All five batches and completion checks are complete on `phase-7-paper-portfolio`.
Baseline: **1873 passed, 2 warnings in 21.68s**. Final Phase 7 + Phase 6 targeted
selection: **414 passed in 43.11s**. Full suite: **2059 passed, 2 warnings in 48.14s**.
Dependency, import/OpenAPI, offline lifecycle, deterministic replay/permutation
and source audits passed. See `docs/PHASE_7_REPORT.md` for rules and exact evidence.
No Phase 1–6 production file, dependency, HTTP route or lifecycle behavior changed.
No Phase 8, commit or push is included.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small reviewable batches, run targeted tests after every meaningful batch, then run the complete backend suite. Do not broadly rewrite previous phases.

Working branch: `phase-7-paper-portfolio`.

Phase 6 is merged into `main`. Accepted starting baseline: **1873 backend tests passing**.

Read completely before editing:
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/PHASE_5_REPORT.md`
- `docs/PHASE_6_REPORT.md`
- `backend/src/domain/backtesting.py`
- `backend/src/application/historical_replay.py`
- `backend/src/application/backtest_engine.py`
- `backend/src/application/backtest_evaluator.py`
- `backend/src/application/backtest_math.py`
- `backend/src/application/backtest_metrics.py`
- `backend/src/application/backtest_identity.py`
- `backend/src/application/decision_engine.py`
- `backend/src/domain/decisions.py`
- `backend/src/application/risk_engine.py`
- `backend/src/domain/models.py`
- `backend/src/infrastructure/paper_execution.py`
- the Phase 6 test suite.

## Objective
Build a deterministic **offline paper-portfolio simulator** over the existing historical analytical pipeline.

Phase 6 validates every eligible signal independently. Phase 7 must answer a different question: what would happen to one shared pool of **virtual capital units** when eligible decisions compete for limited portfolio capacity and positions overlap in time?

Target architecture:

```text
Historical finalized bars
    -> existing HistoricalReplay
    -> existing FeatureEngine
    -> existing StrategyEngine
    -> existing DecisionEngine
    -> HistoricalDecision / DecisionRecord
    -> PaperPortfolioPolicy
    -> deterministic entry reservation / portfolio arbitration
    -> virtual PaperPosition(s)
    -> deterministic close at the configured fixed horizon
    -> PaperPortfolioLedger
    -> equity / exposure / drawdown / rejection metrics
    -> PaperPortfolioReport
```

This is simulation only. A portfolio acceptance is **not** a trade recommendation, order approval, profitability guarantee or permission to use real money.

## Critical architectural decision: do not wire Phase 1 execution contracts into the simulator
The existing Phase 1 `RiskEngine` consumes a concrete `TradeIntent` containing a quantity, keeps process-local approval history, and its `RiskDecision` currently uses a random UUID. The existing `PaperExecutionGateway` consumes `ApprovedTradeIntent` and also produces process-local simulated fills.

Those contracts are execution-oriented and are not the right deterministic historical portfolio primitive for Phase 7.

Therefore Phase 7 must **not**:
- create `TradeIntent` or `ApprovedTradeIntent`,
- call `RiskEngine`,
- call `PaperExecutionGateway`,
- modify `RiskEngine` just to make historical simulation fit,
- modify `PaperExecutionGateway` just to make historical simulation fit.

Instead, create a separate deterministic **PaperPortfolioPolicy** and portfolio-domain contracts using virtual notional/capital units only.

The future architectural boundary remains:

```text
DecisionRecord(ELIGIBLE)
    -> paper/live-independent portfolio/risk research
    -> future explicitly designed intent builder
    -> independent deterministic pre-execution RiskEngine
    -> paper execution only unless a later separately reviewed phase changes scope
```

Do not collapse those boundaries in Phase 7.

## Non-negotiable scope boundaries
Do not add or use:
- Binance API keys, secrets or signed requests,
- private Binance REST/WebSocket endpoints,
- balances, positions or account state from any exchange,
- real-money order submission,
- testnet order submission,
- deposits, withdrawals, transfers or P2P transaction automation,
- exchange order IDs,
- leverage or margin execution,
- liquidation simulation presented as exchange-accurate,
- real quantity sizing,
- `TradeIntent` / `ApprovedTradeIntent`,
- `RiskEngine` approval,
- `PaperExecutionGateway`,
- AI Advisor / OpenAI API,
- ML/RL models,
- automatic parameter optimization,
- grid/genetic/Bayesian search for profitable settings,
- return-based tuning of StrategyEngine or DecisionEngine,
- persistent database/Redis unless strictly necessary (prefer none),
- frontend redesign,
- network downloads of historical market data,
- profitability claims.

Everything must remain deterministic and offline in tests.

## Baseline first
Before editing:
1. confirm `git branch --show-current` is `phase-7-paper-portfolio`;
2. confirm `git status` is clean except for this already-pulled task commit;
3. run the complete backend suite;
4. confirm **1873 tests pass** before implementation;
5. inspect all files listed at the top of this task.

Do not change Phase 1–6 semantics unless a very small compatibility fix is independently justified and tested.

## Core design principles
1. **Shared virtual capital.** Unlike Phase 6, positions compete for one portfolio capacity.
2. **No look-ahead.** Portfolio acceptance, sizing and arbitration may use only information available at decision time.
3. **Next-bar entry.** Preserve the Phase 6 anti-look-ahead entry convention.
4. **Fixed-horizon exit.** Reuse the same explicit holding-horizon semantics as Phase 6.
5. **No leverage.** Gross virtual notional must stay within configured non-leveraged exposure limits.
6. **Transparent deterministic sizing.** No Kelly criterion, optimizer or inferred win probability.
7. **Portfolio risk is separate from strategy confidence.** Confidence remains evidence quality, not a probability of profit.
8. **Deterministic arbitration.** Simultaneous eligible decisions must not depend on input ordering.
9. **Reservation prevents overbooking.** Accepted decisions reserve capacity before next-bar entry.
10. **Conservative missing-data behavior.** Never fabricate a portfolio exit or mark through an unknown required bar.
11. **Explicit cost accounting.** Reuse Phase 6 fee/slippage assumptions rather than creating hidden costs.
12. **Deterministic identities.** No UUIDs for analytical portfolio artifacts.
13. **Immutable report artifacts.** Mutable state may exist inside one finite simulator run only.
14. **No execution semantics.** Names should say paper/virtual/simulated, not approved order/execution.
15. **No claim that historical portfolio results predict future returns.**

## Portfolio settings
Create a frozen, validated `PaperPortfolioSettings` (or similarly clear name) with a small transparent policy.

Preferred defaults:

```text
PORTFOLIO_INITIAL_VIRTUAL_EQUITY=100000
PORTFOLIO_TARGET_POSITION_FRACTION=0.10
PORTFOLIO_MAX_GROSS_EXPOSURE_FRACTION=0.40
PORTFOLIO_MAX_SYMBOL_EXPOSURE_FRACTION=0.15
PORTFOLIO_MAX_OPEN_POSITIONS=4
PORTFOLIO_MAX_DRAWDOWN_FRACTION=0.20
PORTFOLIO_ONE_POSITION_PER_SYMBOL=true
```

All monetary/notional values are abstract **virtual capital units**. Do not label them as actual USDT/USD unless an explicit reporting label says they are hypothetical units.

Validation requirements:
- finite Decimal values only;
- initial equity strictly positive;
- fractions in sensible bounded ranges;
- target position fraction > 0 and <= 1;
- max gross exposure > 0 and <= 1;
- max symbol exposure > 0 and <= max gross exposure;
- max drawdown > 0 and < 1;
- max open positions strict positive integer;
- booleans parsed explicitly from environment;
- extra settings forbidden;
- no negative/NaN/Infinity values.

Do not add more settings unless the existing contracts clearly require them.

## Shared-capital sizing policy
Sizing is virtual notional sizing, not exchange quantity sizing.

At each decision time define a deterministic sizing basis from currently known portfolio state. Prefer **marked virtual equity** if the mark calculation is implemented safely; otherwise use an explicitly named realized-equity basis and document the limitation.

Preferred desired notional:

```text
desired_notional = sizing_equity * target_position_fraction
```

The desired notional must fit all configured limits, including reservations:
- maximum gross exposure,
- maximum per-symbol exposure,
- maximum open position count,
- one-position-per-symbol rule,
- drawdown halt,
- positive-equity requirement.

Prefer **all-or-none capacity allocation** in Phase 7: if the desired notional does not fully fit the configured limits, reject the eligible decision with an explicit reason rather than silently shrinking it. This keeps comparisons auditable.

Do not use confidence as a multiplier for size in Phase 7. Do not interpret confidence as probability.

## Portfolio risk gates
PaperPortfolioPolicy should be a pure deterministic gate over:
- a valid Phase 5 `DecisionRecord`,
- current immutable portfolio state/snapshot,
- configured `PaperPortfolioSettings`,
- explicit evaluation time where relevant.

Only `DecisionOutcome.ELIGIBLE` can be considered for a reservation.

Stable rejection/ignore reasons should cover at minimum:
- `decision_not_eligible` for BLOCKED/NO_ACTION diagnostic decisions,
- `portfolio_drawdown_limit`,
- `nonpositive_equity`,
- `max_open_positions`,
- `gross_exposure_limit`,
- `symbol_exposure_limit`,
- `symbol_position_active`,
- `duplicate_decision`,
- `invalid_or_stale_portfolio_state`,
- `missing_entry_bar` / reservation expiry where appropriate.

Do not change the upstream DecisionRecord outcome. A Phase 5 ELIGIBLE decision may be rejected by the portfolio policy while remaining ELIGIBLE upstream.

## Simultaneous-decision arbitration
Multiple symbols may produce eligible decisions at the same timestamp and available capacity may be insufficient for all of them.

Do not let arbitrary iterator/input order decide who gets capacity.

Collect decisions sharing the same decision timestamp and evaluate them as one deterministic batch after the market state for that timestamp is fully known.

Use a small documented arbitration key based only on information available at that timestamp. Prefer:

```text
1. larger absolute composite_score first
2. higher confidence
3. higher agreement
4. symbol lexical order
5. decision_id lexical order
```

Do not claim this ranking predicts returns. It is only a deterministic tie/capacity policy.

Test that permuting equal-time input ordering yields the same portfolio reservations and report.

## Reservation semantics
A portfolio-accepted decision creates a deterministic **PaperEntryReservation** for the next expected bar open of that symbol.

Reservations:
- count against gross/symbol capacity immediately,
- prevent simultaneous accepted decisions from overbooking future entry capacity,
- have deterministic IDs,
- contain decision ID, symbol, direction, planned virtual notional, decision time and expected entry time,
- contain no exchange quantity/order fields,
- expire/cancel if the required next bar is missing,
- never become a real order.

If the next expected bar exists, the reservation becomes a virtual `PaperPosition` at that bar's raw open using the same adverse-entry cost assumptions as Phase 6.

A reservation must not be created twice for the same decision identity.

## Position semantics
Create immutable output/domain models and a finite-run mutable ledger/service.

Prefer concepts close to:

```text
PortfolioAction = IGNORED | REJECTED | RESERVED
PortfolioDecisionRecord
PaperEntryReservation
PaperPosition
PaperPositionClose
PaperPortfolioCurvePoint
PaperPortfolioMetrics
PaperPortfolioRunMetadata
PaperPortfolioReport
```

`PaperPosition` should contain only simulation fields such as:
- deterministic position_id,
- reservation_id / decision_id,
- symbol,
- LONG/SHORT direction,
- decision_time,
- entry_time,
- raw entry price,
- virtual notional,
- configured horizon,
- bars held / expected next bar time,
- deterministic policy/settings provenance.

Do not include exchange account IDs, API credentials, margin, leverage, order types or real quantity.

Prefer one open position per symbol by default. New same-symbol signals while a position/reservation exists are rejected and recorded; do not pyramid in Phase 7.

Do not automatically reverse a position on an opposite signal.

## Entry/exit and cost model
Preserve Phase 6 conventions:
- decision from finalized bar `t`,
- entry at `open(t+1)`,
- fixed horizon of H complete bars,
- exit at `close(t+H)`,
- H comes from the existing `BacktestSettings` or an explicitly reused compatible configuration,
- every required horizon bar must exist.

Reuse Phase 6 deterministic cost math (`outcome_returns`) where practical instead of reimplementing a slightly different fee/slippage formula.

At a completed close:

```text
virtual_pnl = position_virtual_notional * net_return
```

where `net_return` is the same two-sided fee/slippage-adjusted signal return defined and tested in Phase 6.

Store separately:
- gross hypothetical PnL,
- simulated fee cost,
- simulated slippage cost,
- total simulated cost,
- net hypothetical PnL.

Do not silently double-count entry/exit costs.

## Mark-to-market equity
Prefer implementing marked virtual equity because drawdown gates should reflect known open-position losses rather than only completed positions.

If implemented, define it explicitly and conservatively.

At bar close for an open position, use only that bar's current close and information already known. A simple acceptable model is:
- directional gross return from raw entry to current raw close;
- subtract entry-side slippage and entry-side fee already incurred;
- do **not** charge exit-side cost until the position actually exits;
- no post-bar or future price may enter the mark.

Then:

```text
realized_equity = initial_virtual_equity + cumulative_closed_net_pnl
marked_equity = realized_equity + sum(current_known_unrealized_net_pnl)
```

Document exact formulas and test LONG/SHORT independently.

If exact marked-equity implementation would be ambiguous or inconsistent with Phase 6 costs, defer marked equity and use an explicitly named realized-equity policy instead. Do not implement a misleading mark formula.

## Equity peak and drawdown gate
Track a deterministic portfolio equity peak using the selected documented equity basis.

Drawdown:

```text
drawdown = max(0, (peak_equity - current_equity) / peak_equity)
```

When drawdown is **>= configured max drawdown**, block new reservations until the selected equity basis recovers below the threshold. Existing virtual positions continue according to their fixed horizon; do not fabricate emergency liquidation.

Do not add dynamic stop-loss or liquidation in Phase 7.

## Exposure accounting
Track at minimum:
- open virtual notional,
- reserved virtual notional,
- gross exposure = open + reserved notional,
- gross exposure fraction relative to the documented equity basis,
- per-symbol open + reserved exposure,
- open position count,
- reservation count.

Gross exposure is absolute notional; LONG and SHORT do not cancel each other for risk-limit purposes.

No leverage means the configured max gross exposure must never exceed 1.0.

## Missing bars and gaps
Portfolio accounting must never invent prices.

Reservation gap:
- if the exact next entry bar is missing, cancel/expire the reservation with an explicit reason;
- no position is opened;
- reserved capacity is released.

Open-position gap before its required horizon is more serious because the simulator cannot know the missing mark/path.

Use a fail-closed deterministic behavior. Preferred approach:
- mark that position unresolved/incomplete,
- mark the portfolio run `INCOMPLETE` (or equivalent explicit status),
- do not fabricate an exit, return or final marked equity for the unresolved exposure,
- continue only if the report semantics remain truthful; otherwise stop the run cleanly and report where it became incomplete.

Do not forward-fill a price through a missing required bar.

Tests must cover missing entry and missing horizon data separately.

## Empty / insolvent states
Handle explicitly:
- empty dataset,
- zero eligible decisions,
- all portfolio-rejected eligible decisions,
- dataset ending with pending reservations,
- dataset ending with open positions,
- virtual equity <= 0 due to a modeled SHORT/market move.

If virtual equity becomes nonpositive:
- block all new reservations,
- do not clamp equity to zero,
- do not claim exchange liquidation behavior,
- preserve the actual simulated negative/zero value where model validation permits,
- clearly flag insolvency/unsupported-realism limitation.

## Deterministic identity contract
Do not use random UUIDs.

Use/extend the existing canonical identity helper.

Prefer identities similar to:

```text
portfolio_policy_id = hash(validated portfolio settings + version)
portfolio_decision_id = hash(policy_id, upstream decision_id, portfolio state identity, action/reason)
reservation_id = hash(policy_id, decision_id, expected_entry_time, virtual_notional)
position_id = hash(reservation_id, normalized entry-bar evidence)
close_id = hash(position_id, normalized exit/horizon evidence, cost settings)
portfolio_run_id = hash(
    portfolio_engine_version,
    dataset_id,
    feature_settings_id,
    strategy_settings_id,
    decision_policy_id,
    backtest_settings_id,
    portfolio_policy_id,
    symbols,
    interval
)
```

Equivalent dataset + settings must produce byte-for-byte equivalent report serialization where existing Pydantic ordering allows it.

Changed portfolio settings or dataset must change the relevant identities.

## Portfolio curve
Create a chronological curve using the documented equity basis.

Each point should contain enough provenance to audit the state, preferably:
- timestamp,
- realized equity,
- marked equity if implemented,
- peak equity,
- drawdown,
- open position count,
- reservation count,
- gross exposure,
- gross exposure fraction,
- cumulative gross PnL,
- cumulative simulated costs,
- cumulative net PnL.

Equal-time updates must follow one documented deterministic event order.

Prefer one canonical portfolio snapshot per completed market timestamp after:
1. entries due at that timestamp open are applied,
2. bar-close marks/exits are processed,
3. all same-time decisions are arbitrated and reservations created.

Document the exact sequence and test it.

## Metrics
Create pure deterministic portfolio metrics, distinct from Phase 6 independent signal metrics.

Required metrics should include at minimum:
- input bar count,
- evaluated decision count,
- upstream ELIGIBLE/BLOCKED/NO_ACTION counts,
- portfolio accepted/reserved count,
- portfolio rejected count,
- ignored diagnostic decision count,
- opened position count,
- completed position count,
- unresolved/incomplete position count,
- missing-entry reservation count,
- LONG/SHORT opened counts,
- initial virtual equity,
- final realized equity,
- final marked equity when defined,
- total gross PnL,
- total simulated fee cost,
- total simulated slippage cost,
- total simulated costs,
- total net PnL,
- realized total return relative to initial equity,
- peak equity,
- maximum portfolio drawdown on the documented equity basis,
- maximum gross exposure,
- maximum gross exposure fraction,
- maximum simultaneous open positions,
- average open-position count across curve snapshots if implemented cleanly,
- turnover = sum opened virtual notional / initial virtual equity (clearly documented),
- win/loss/flat completed positions,
- win rate excluding flats,
- per-symbol completed PnL and counts,
- portfolio rejection counts by stable reason.

Do not call Phase 6's additive normalized signal-return curve an account curve. Phase 7 is the first shared-capital curve, but it is still a virtual simplified portfolio model.

Sharpe/Sortino are optional and should be deferred unless sampling-frequency/annualization semantics are fully explicit and independently tested.

## Relationship to Phase 6
Do not replace Phase 6.

Phase 6 remains useful for measuring every eligible signal independently.

Phase 7 adds a second interpretation:

```text
Phase 6: signal-level outcome quality
Phase 7: shared-capital portfolio feasibility/risk under overlapping signals
```

Where practical, reuse:
- `HistoricalReplay`,
- historical bar validation/ordering,
- `BacktestSettings` holding horizon and fee/slippage settings,
- `outcome_returns`,
- dataset identity helpers,
- deterministic Phase 4/5 identities.

Do not duplicate indicator, strategy, decision or fee formulas.

## Suggested structure
Prefer a compact structure close to:

```text
backend/src/domain/
  paper_portfolio.py

backend/src/application/
  paper_portfolio_settings.py
  paper_portfolio_identity.py
  paper_portfolio_policy.py
  paper_portfolio_ledger.py
  paper_portfolio_metrics.py
  paper_portfolio_engine.py
```

Adjust names after inspection if a simpler design fits the repository better.

Avoid a giant all-in-one service.

## API / lifecycle
Phase 7 is offline validation infrastructure.

Do **not** add a live HTTP mutation API.

Prefer no new FastAPI routes at all. Existing OpenAPI path count should remain unchanged.

Do not add background tasks to the application lifespan. Historical portfolio simulation should be explicitly invoked by code/tests, as Phase 6 backtesting is.

Import must remain side-effect free and no network call may occur.

## Testing requirements
Add comprehensive deterministic offline tests. Expected tests should not calculate their expected answer by calling the same production helper under test.

### Batch 1 — domain/settings/pure sizing math
Implement and test:
- immutable portfolio models,
- setting validation,
- extra-field rejection,
- NaN/Infinity rejection,
- deterministic settings/policy IDs,
- desired-notional formula,
- all-or-none capacity checks,
- gross/symbol exposure math,
- LONG/SHORT mark math if marked equity is implemented,
- drawdown formula and exact threshold boundary,
- no executable/order/account fields.

### Batch 2 — PaperPortfolioPolicy + arbitration
Implement and test:
- ELIGIBLE can be accepted when capacity exists,
- BLOCKED/NO_ACTION ignored diagnostically,
- duplicate decision refused/deduped deterministically,
- max-open-position gate,
- gross-exposure gate,
- symbol-exposure gate,
- one-position-per-symbol gate,
- nonpositive-equity gate,
- drawdown gate exactly at threshold,
- reservation counts toward capacity,
- equal-time arbitration independent of input order,
- arbitration score/confidence/agreement/symbol tie boundaries,
- upstream DecisionRecord remains unmodified.

### Batch 3 — ledger, reservations, entries, exits
Implement and test:
- reservation at decision t,
- exact entry at next bar open,
- no same-bar fill,
- missing next bar releases reservation without position,
- exact fixed H-bar exit,
- H=1 boundary,
- LONG/SHORT PnL symmetry examples,
- Phase 6 fees/slippage reused consistently,
- no double-counted costs,
- overlapping positions across different symbols,
- same-symbol signal rejected while position/reservation active,
- deterministic position/close IDs,
- data gap with open exposure fails closed/incomplete,
- dataset end with open position is explicit and not fabricated.

### Batch 4 — portfolio curve + metrics
Implement and independently test:
- realized equity reconciliation,
- marked equity reconciliation if supported,
- peak equity,
- drawdown and maximum drawdown,
- gross exposure curve,
- max simultaneous positions,
- cumulative gross/cost/net PnL,
- turnover,
- win/loss/flat counts,
- per-symbol PnL/counts,
- rejection-reason counts,
- empty dataset,
- no eligible decisions,
- all rejected,
- insolvency/nonpositive-equity state,
- report count reconciliation.

### Batch 5 — end-to-end deterministic portfolio replay
Use deterministic synthetic multi-symbol historical bars and the actual production:

```text
HistoricalReplay
 -> FeatureEngine
 -> StrategyEngine
 -> DecisionEngine
 -> PaperPortfolioEngine
```

Test:
- no look-ahead prefix invariance,
- same-time multi-symbol arbitration is stable under input permutation,
- repeated identical run produces identical portfolio decisions, reservations, positions, curve, IDs and serialized report,
- changed portfolio policy changes policy/run IDs,
- changed market data changes dataset/run IDs,
- Phase 6 independent signal report remains unchanged by Phase 7,
- bounded feature history remains intact,
- no task/subscriber leaks after cancellation/error,
- no network calls,
- existing OpenAPI routes unchanged,
- all Phase 1–6 tests remain intact.

## Scope/security audit tests
Explicitly assert/review that Phase 7 production modules:
- do not import Binance private/account APIs,
- do not import or construct `TradeIntent`,
- do not import or construct `ApprovedTradeIntent`,
- do not import/call `RiskEngine`,
- do not import/call `PaperExecutionGateway`,
- do not submit orders,
- do not request API keys,
- do not expose account/balance fields,
- do not implement P2P transfers,
- do not add leverage/margin/liquidation execution,
- do not add AI/OpenAI/ML/RL,
- do not add parameter optimization,
- do not add network-dependent tests.

## Documentation
Update:
- `CODEX_TASK.md` implementation status at completion,
- `docs/ARCHITECTURE.md`,
- `backend/README.md`,
- root `README.md` only if useful.

Create:
- `docs/PHASE_7_REPORT.md`.

Document exactly:
- why Phase 7 is separate from Phase 6 signal validation,
- why Phase 1 RiskEngine/PaperExecutionGateway are intentionally not wired into historical portfolio simulation,
- virtual-capital semantics,
- settings/defaults,
- sizing formula,
- risk gates,
- simultaneous-decision arbitration,
- reservation semantics,
- event ordering,
- entry/exit horizon,
- cost model,
- equity/mark formulas,
- exposure formulas,
- drawdown gate,
- missing-bar behavior,
- deterministic identity contract,
- metrics,
- limitations,
- insolvency behavior,
- why this is not an exchange-accurate account/margin model,
- no profitability claim.

## Final validation
After all batches:
1. run all Phase 7 targeted tests;
2. run complete `python -m pytest`;
3. run `python -m pip check`;
4. run import/OpenAPI validation and confirm existing GET path count is unchanged;
5. run offline lifespan smoke tests and confirm zero leaked tasks/subscribers;
6. run the same deterministic portfolio replay twice and compare IDs plus serialized report bytes;
7. run an equal-time multi-symbol input-permutation test and confirm same portfolio output;
8. run `git diff --check`;
9. inspect `git status`;
10. inspect `git diff --stat`;
11. audit new production modules for prohibited execution/private/account/AI/optimization references.

## Completion report
At completion report:
1. exact baseline result;
2. each batch result;
3. final targeted result;
4. exact full-suite result;
5. files created;
6. files modified;
7. portfolio architecture;
8. settings/defaults;
9. exact sizing semantics;
10. exact risk gates;
11. arbitration order;
12. reservation behavior;
13. entry/exit/cost behavior;
14. equity and drawdown formulas;
15. missing-data behavior;
16. deterministic identity behavior;
17. portfolio metrics;
18. end-to-end determinism evidence;
19. lifecycle/network evidence;
20. warnings;
21. deferred work;
22. remaining technical risks;
23. `git status`;
24. `git diff --stat`.

Do **not** commit or push automatically.

Do **not** start Phase 8.

## Explicitly deferred after Phase 7
Defer:
- exchange/private/account integration,
- real-money execution,
- testnet order submission,
- P2P automation,
- exchange-accurate margin/liquidation/funding,
- real quantity/lot-size sizing,
- stop-loss/take-profit order placement,
- dynamic exits,
- strategy/decision parameter optimization,
- AI/ML/RL,
- persistent audit/database layer,
- production portfolio execution orchestration.

Phase 7 ends when a deterministic, well-tested **offline shared-capital paper portfolio report** exists and all previous phases still pass.
