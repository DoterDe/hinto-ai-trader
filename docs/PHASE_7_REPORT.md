# Phase 7 — Deterministic Paper Portfolio & Risk Simulation

## Scope and baseline

Implemented on `phase-7-paper-portfolio`, starting at `9a22c87`. The branch was
up to date with its tracking branch and the working tree was clean. AGENTS.md,
CODEX_TASK.md, architecture, Phase 5/6 reports, required production contracts and
all Phase 6 tests were read before edits. The repository virtual environment
(Python 3.11.9, pytest 8.4.2 on Windows) passed the complete baseline:

```text
python -m pytest
1873 passed, 2 warnings in 21.68s
```

All five implementation batches and final validation are complete. The full suite
passed **2059 tests with the same two dependency warnings in 48.14s**: all 1873
baseline tests plus 186 Phase 7 additions. Exact ancillary results appear below.
Nothing is committed or pushed; no Phase 8 work is included.

## Architecture and compatibility

```text
finalized historical KlineEvent iterator
  -> unchanged HistoricalReplay / MarketDataHub
  -> unchanged FeatureEngine -> StrategyEngine -> DecisionEngine
  -> immutable HistoricalDecision / DecisionRecord
  -> same-time grouping -> PaperPortfolioLedger
       -> due reservations become virtual positions
       -> known close marks / fixed-horizon exits
       -> pure PaperPortfolioPolicy arbitration / new reservations
  -> immutable state / curve / metrics -> PaperPortfolioReport
```

Phase 6 evaluates every eligible signal independently. Phase 7 makes those
signals compete for one pool of **virtual capital units**. Neither replaces the
other. Existing production code and analytical defaults remain unchanged. The
only existing Python edit is adding `PORTFOLIO_` to test environment isolation.
There are no dependency, API or application lifespan changes.

Phase 1 RiskEngine and PaperExecutionGateway are intentionally not connected.
Their contracts consume quantity-bearing executable intents, retain process-local
approval/fill state and use execution identities unsuitable for deterministic
historical artifacts. Phase 7 has its own pure PaperPortfolioPolicy. It never
creates TradeIntent/ApprovedTradeIntent or calls either execution service. A
future explicitly designed intent builder and independent pre-execution risk
review remain separate work.

## Settings, sizing and gates

`PaperPortfolioSettings` is frozen, finite, revalidated and rejects extra fields.
It reads `PORTFOLIO_` process variables without automatically loading `.env`.

| Suffix | Default | Validation |
| --- | --- | --- |
| `INITIAL_VIRTUAL_EQUITY` | 100000 | Strictly positive finite Decimal |
| `TARGET_POSITION_FRACTION` | 0.10 | `(0,1]` |
| `MAX_GROSS_EXPOSURE_FRACTION` | 0.40 | `(0,1]` |
| `MAX_SYMBOL_EXPOSURE_FRACTION` | 0.15 | `(0,max gross]` |
| `MAX_OPEN_POSITIONS` | 4 | Strict positive integer |
| `MAX_DRAWDOWN_FRACTION` | 0.20 | `(0,1)` |
| `ONE_POSITION_PER_SYMBOL` | true | Explicit true/false parsing; false is unsupported |

Rejecting false is deliberate: the task excludes pyramiding and reversal. The
flag does not silently enable a second same-symbol position. Boolean values in
numeric settings, fractional position counts, NaN/Infinity and invalid ranges fail.

Desired virtual notional is `marked_equity * target_position_fraction`. No
confidence multiplier, Kelly sizing, inferred win probability or partial allocation
exists. Confidence is upstream evidence quality. At the pure policy boundary,
malformed contracts raise; coherent decisions get a stable action/reason:

1. Explicit duplicate reads: IGNORED / `duplicate_decision`.
2. BLOCKED/NO_ACTION: IGNORED / `decision_not_eligible`.
3. State/decision time not equal to explicit current time, or unknown marked
   equity: REJECTED / `invalid_or_stale_portfolio_state`.
4. Equity <= 0: `nonpositive_equity`.
5. Drawdown >= the limit: `portfolio_drawdown_limit`.
6. Existing same-symbol position/reservation: `symbol_position_active`.
7. Open-plus-reserved count at its limit: `max_open_positions`.
8. Existing gross plus desired notional above equity times gross limit:
   `gross_exposure_limit`.
9. Existing symbol exposure plus desired notional above its limit:
   `symbol_exposure_limit`.
10. Otherwise RESERVED / `capacity_reserved`.

One first failing reason is retained in that order, along with state/policy IDs
and the unchanged upstream DecisionRecord. Exposure equality passes; drawdown
equality blocks. Readiness/freshness in upstream engines is never bypassed. The
portfolio additionally requires a current historical decision and portfolio state;
it does not invent a new permissive age setting.

## Arbitration, reservations and event order

All decisions at one timestamp are collected before capacity is allocated. Rank
by descending absolute composite score, confidence and agreement; then ascending
symbol and decision ID. These fields are available at decision time. The rank is
a deterministic capacity policy, not a return forecast. Pure tests cover all 24
permutations of four decisions; end-to-end tests also compare multi-symbol input
permutations and complete report bytes.

Each accepted reservation immediately consumes gross/symbol notional and a
position-count slot. Each later decision in the same ranked batch sees that
reserved capacity. Reservations fix notional before the next bar's prices are
known. There is no double-counted open-plus-reserved exposure: conversion removes
the pending reservation before adding its position.

For each complete market timestamp, the ledger applies previously reserved
entries from those bars' opens, processes all known close marks/exits, and then
arbitrates the current timestamp's decisions. Thus capacity released by a close
is available for a new reservation at that close, whose entry belongs to the
following bar. Opposite signals do not close or reverse existing positions.

HistoricalReplay retains its existing bar validation, lexical symbol ordering,
simulated clock, warm-up, gaps and bounded-history behavior. The portfolio grouping
layer may hold one next-time frame to delimit a group, but passes only the group's
immutable bars/decisions to the ledger. The policy cannot read the replay provider
or future frame. Future-price mutation tests verify earlier decisions, sizing,
reservations and curve points are unchanged. No future outcomes enter selection.

## Entry, horizon, costs and equity

Source bar t reserves at its exclusive close; entry is **open(t+1)** and exit
**close(t+H)**. H=5 by default via unchanged BacktestSettings; H=1 opens and closes
within the next bar. Minute source `[00:00,00:01)` enters at 00:01 and exits at
00:06 for H=5. The next open price need not equal the source close. Entries are
represented when finalized next-bar observations arrive. This is the explicit
bar-end availability/zero-latency assumption, not an exchange fill claim.

All H consecutive bars are required, including true calendar-month boundaries.
No horizon shifts past missing bars, no dynamic stops/targets and no liquidation
occur. Costs reuse Phase 6 defaults: 5 bps fee and 2 bps adverse slippage per side.
Let N=virtual notional, E=raw entry, X=raw exit, C=current known close,
d=+1 LONG/-1 SHORT, s=slippage_bps/10000 and f=fee_bps/10000:

```text
E' = E*(1+d*s); X' = X*(1-d*s)
gross_return = d*(X-E)/E
slippage_return = s*(1+X/E)
fee_return = f*(E'+X')/E
net_return = gross_return-slippage_return-fee_return
closed gross/fee/slippage/total/net PnL = N * corresponding Phase 6 return

gross_mark = N * [d*(C-E)/E]
entry_slippage = N*s
entry_fee = N*f*(1+d*s)
unrealized_net = gross_mark-entry_slippage-entry_fee
realized_equity = initial_virtual_equity + cumulative_closed_net_pnl
marked_equity = realized_equity + sum(current_known_unrealized_net)
```

`closed_pnl` calls existing `outcome_returns`; it does not duplicate its formula.
Open marks charge entry costs only. On close, the unrealized mark is removed and
full two-sided net PnL is realized once. Independent N=10000, E=100 examples:
LONG C=110 has open marked PnL 992.999 and closed PnL 985.3001; SHORT C=90 has
open marked PnL 993.001 and closed PnL 986.7001. These are arithmetic fixtures.

Arithmetic uses the existing isolated 34-digit Decimal context and rejects
nonfinite/unrepresentable values. PnL components reconcile within
`1e-32 * largest absolute component`, allowing only final-digit differences from
independent notional multiplication. Net remains the calculated `N*net_return`.
No finite-value clamping or hidden rebate is added.

Peak equity starts at initial capital and takes the maximum of known canonical
marked-equity observations. Drawdown is `(peak-current)/peak`, with a positive
peak; at or above the configured limit new reservations block until recovery.
Existing positions keep their fixed horizons. Zero/negative virtual equity is
preserved, flagged and blocks new capacity; there is no exchange liquidation model.

Gross exposure is fixed open notional plus reserved notional; per-symbol exposure
uses the same sum. LONG and SHORT do not cancel. Fraction is gross/marked equity
only while that equity is known and positive, otherwise null. Limits gate new
reservations; losses/costs can passively increase existing fractions above limits
or one. Pretending otherwise would require forced resizing/liquidation contrary
to the task. No borrowed capital or leverage operation is implemented.

## Missing data and terminal state

A missing exact next bar expires the reservation with `missing_entry_bar`,
releases capacity and creates no position. Dataset-end pending reservations expire
with `dataset_ended`. A required holding-bar gap marks the position INCOMPLETE /
`missing_horizon_bar`, retains unresolved notional, and makes total marked equity,
drawdown and exposure fraction unavailable. Old marks are not forward-filled.
Later prices do not repair the unknown holding path. The run continues reporting
diagnostics; new reservations block and other existing positions can finish if
their own required bars remain present.

At dataset end, still-open positions become INCOMPLETE / `dataset_ended`, with no
invented exit or final mark. Last observed mark time/price remain diagnostic on
the position, and previously recorded as-of curve points are not rewritten.
`final_state` separately shows released reservations and unresolved exposure.
Any expiry or incomplete position makes report status INCOMPLETE. A reservation
expiry alone can still leave final marked equity fully defined. Empty input has
no fabricated timestamp/curve/final state and reports initial equity.

## Identity and audit contracts

Models are frozen, reject extra fields, revalidate nested instances and reject
nonfinite numbers. Domain artifacts carry no executable quantity, order, account,
credential, margin or leverage fields. Policy decisions retain their upstream
record exactly. Phase 6 DecisionCapture supplies run-local identity suppression;
duplicate reads increment metadata rather than creating extra reservations or
outcomes. Conflicting identity reuse fails closed.

- Policy ID hashes validated portfolio settings and policy version.
- Portfolio decision ID hashes policy, upstream decision ID, current state ID,
  action and reason.
- Reservation ID hashes policy, upstream ID, expected next-open time and notional.
- Position ID hashes reservation, normalized observed entry-bar evidence and
  backtest settings. The artifact is recorded from a finalized bar; the entry-bar
  close can affect its evidence ID but cannot affect pre-existing sizing.
- Close ID hashes position, incrementally hashed full horizon evidence and costs.
- Run ID hashes portfolio/backtest/analytical versions, normalized dataset ID,
  all four analytical/backtest configuration IDs, portfolio policy and symbol/
  interval scope. `metadata.run_id` is the report identity; no UUID or wall clock.

Equivalent inputs/configuration produce identical bytes in the tested environment.
Settings hashes are provenance, not full embedded configuration or cryptographic
authentication. Retain configurations and code revision with the report. Reused
BacktestSettings includes its segment field in identity even though Phase 7 does
not perform Phase 6 segment reporting.

## Curve and metrics

An initial equity anchor precedes one canonical point per completed market
timestamp, after entries, marks/exits and arbitration. Points retain state,
cumulative closed PnL and pre-exit open count, including H=1 round trips. Metrics
are pure and independently tested against hand-built artifacts and expected values:

- Input bars; evaluated unique decisions; upstream eligible/blocked/no-action;
  reserved/rejected/ignored; opened/completed/incomplete; missing-entry reservations
  (including dataset-end expiry); LONG/SHORT opened counts.
- Initial equity; final realized/marked equity; `total_closed_pnl` with distinct
  gross, fee, slippage, total-cost and net fields. Outstanding incomplete-position
  entry fee/slippage costs are separate, not added twice to realized PnL.
- Realized total return = closed net PnL / initial equity.
- Peak equity; maximum known close-snapshot drawdown; maximum snapshot gross
  notional; `max_observed_gross_exposure_fraction` over defined positive-equity
  observations. These do not claim an unknown/intrabar maximum.
- Maximum simultaneous open count includes `open_count_before_exits`. Average
  open count is the arithmetic mean of canonical close-snapshot counts excluding
  the initial anchor. Reservations are not counted as opened positions.
- Turnover = sum opened virtual notional / initial equity (entry-notional turnover).
- Completed win/loss/flat use net PnL >0/<0/=0. Win rate = wins/(wins+losses),
  excluding flats, null at zero denominator.
- Per-symbol opened/completed/incomplete counts and closed PnL; rejection counts
  by stable reason. Diagnostic and duplicate reads never generate PnL.
- `valuation_complete` flags unknown/unfinished valuation;
  `nonpositive_equity_observed` flags known insolvency without clamping.

Decision, reservation, position and close identities/provenance are checked for
duplicates/mismatches. Counts reconcile exactly; curve cumulative PnL and realized
equity must agree with closes by timestamp. Final equity and unresolved notional
must agree with finalized positions. This is a shared virtual-capital model, not
the additive independent-signal curve of Phase 6 or an exchange-accurate account.

## Tests and validation

All commands used `.venv/Scripts/python.exe` from `backend`:

| Stage | Exact result |
| --- | --- |
| Baseline full suite | 1873 passed, 2 warnings in 21.68s |
| Batch 1 contracts/math | 107 passed in 0.39s |
| Batch 2 policy + Batch 1 | 135 passed in 0.60s |
| Batch 3 ledger + prior portfolio + Phase 6 math | 198 passed in 0.87s |
| Batch 4 metrics + prior portfolio | 166 passed in 0.86s |
| Initial Batch 5 attempt | 11 passed, 1 warning, 1 teardown error in 24.43s |
| Corrected Batch 5 integration | 11 passed in 24.84s |
| Final accounting/clock/calendar checks | 173 passed in 0.96s |
| Complete Phase 7 + complete Phase 6 selection | 414 passed in 43.11s |
| Final complete backend suite | 2059 passed, 2 warnings in 48.14s |

The teardown error was test guard scope: pytest-asyncio initializes Windows'
internal loopback socket pair after the test, while the guard was still installed.
The guard now wraps all actual portfolio replay work and is restored before
framework teardown. No application network allowance or test assertion was removed.
The temporary unraisable-exception warning disappeared on the successful rerun.

Final additions comprise **186 Phase 7 tests**: 110 contracts/math, 28 policy,
20 ledger, 15 metrics and 13 integration/scope tests. The combined 414-test result
includes all **228 Phase 6 tests**. Exact commands, in order:

```text
python -m pytest
python -m pytest tests/test_paper_portfolio_contracts.py
python -m pytest tests/test_paper_portfolio_policy.py tests/test_paper_portfolio_contracts.py
python -m pytest tests/test_paper_portfolio_ledger.py tests/test_paper_portfolio_policy.py tests/test_paper_portfolio_contracts.py tests/test_backtest_math.py
python -m pytest tests/test_paper_portfolio_metrics.py tests/test_paper_portfolio_ledger.py tests/test_paper_portfolio_policy.py tests/test_paper_portfolio_contracts.py
python -m pytest tests/test_paper_portfolio_engine.py
python -m pytest tests/test_paper_portfolio_engine.py
python -m pytest tests/test_paper_portfolio_contracts.py tests/test_paper_portfolio_policy.py tests/test_paper_portfolio_ledger.py tests/test_paper_portfolio_metrics.py
python -m pytest tests/test_paper_portfolio_contracts.py tests/test_paper_portfolio_policy.py tests/test_paper_portfolio_ledger.py tests/test_paper_portfolio_metrics.py tests/test_paper_portfolio_engine.py tests/test_backtest_contracts.py tests/test_backtest_math.py tests/test_historical_replay.py tests/test_backtest_evaluator.py tests/test_backtest_metrics.py tests/test_backtest_engine.py
python -m pytest
python -m pip check
```

Integration covers actual production decisions, shared capacity, repeated report
serialization, permutations, future-prefix invariance, missing entry/holding bars,
tail exposure, unchanged Phase 6 output and cancellation/input-error cleanup.
A 650-bar single-pass fixture confirms one analytical evaluation per bar and the
unchanged 500-candle feature-history bound. Network guards wrap replay; source
audit tests prohibit execution/private/network/AI/optimizer/persistence imports.

### Final ancillary checks

- `python -m pip check`: **No broken requirements found.**
- Application import and `app.openapi()` under socket/task guards: passed;
  exactly the existing **10 GET paths**, finite JSON, empty application state and
  no network connection or background-task creation at import.
- Offline lifespan, both disabled public feed and injected local source: passed;
  **10 HTTP 200 responses in each case**, default paper mode, real-money execution
  and AI risk bypass false. Shutdown left **zero tasks and zero subscribers**;
  the injected source and feature consumer were cancelled cleanly.
- Standalone portfolio replay: two identical runs plus reversed and rotated
  equal-time symbol permutations produced identical full report bytes, decisions,
  reservations, positions, closes, curve and IDs. These four runs and both lifespan
  cases made **zero external network connection attempts** under socket guards.
- Source audit: all eight new production modules parsed and reviewed for imports,
  calls, executable/account fields, endpoints and nondeterministic clocks/IDs.
  No prohibited integration was found. Changed-file credential-pattern scanning
  found no key material; new Python and whitespace checks passed.
- Repository scope: **15 created files, 5 modified files, nothing staged**.
  No Phase 1–6 production, dependency, application lifecycle or API file changed.
  Final `git diff --check`, branch, status and diff statistics were inspected.

The standalone synthetic fixture used 80 one-minute bars for each of BTCUSDT,
ETHUSDT and SOLUSDT, default analytical/cost settings and
`PaperPortfolioSettings(max_open_positions=1)` to force capacity competition:

```text
input bars / unique decisions: 240 / 240
reservations / positions / closes: 1 / 1 / 1
curve points: 81
status: COMPLETE
serialized UTF-8 report size: 431705 bytes
run_id: paper_portfolio_run_096b4a7fc6cc459a8a366673ea9f8dac605cafd5e183e8458059487f2dd44323
report SHA-256: 4a67ddb47ddf2948a86bfac911864f62e61f72fa5124d12d3154abd780c443fd
```

Ancillary Python checks were run through the repository virtual environment with
inline stdin scripts. Windows asyncio's internal loopback pair was initialized
before applying the network guards; all actual replay/lifespan work remained
guarded. The separate pure-policy test checks all 24 permutations of four decisions.

The two full-suite warnings are unchanged from baseline:

1. Starlette TestClient deprecates its `httpx` integration in favor of `httpx2`.
2. `anyio.abc.BlockingPortal` is deprecated in favor of
   `anyio.from_thread.BlockingPortal`.

No dependency upgrade was made as part of Phase 7. Git also reports existing
LF-to-CRLF conversion notices for the five modified tracked files; these are
line-ending notices, not test failures or whitespace-check failures.

## Files created and modified

Created:

- `backend/src/domain/paper_portfolio.py`
- `backend/src/application/paper_portfolio_settings.py`
- `backend/src/application/paper_portfolio_identity.py`
- `backend/src/application/paper_portfolio_math.py`
- `backend/src/application/paper_portfolio_policy.py`
- `backend/src/application/paper_portfolio_ledger.py`
- `backend/src/application/paper_portfolio_metrics.py`
- `backend/src/application/paper_portfolio_engine.py`
- `backend/tests/portfolio_fixtures.py`
- `backend/tests/test_paper_portfolio_contracts.py`
- `backend/tests/test_paper_portfolio_policy.py`
- `backend/tests/test_paper_portfolio_ledger.py`
- `backend/tests/test_paper_portfolio_metrics.py`
- `backend/tests/test_paper_portfolio_engine.py`
- `docs/PHASE_7_REPORT.md`

Modified: `backend/tests/conftest.py` (environment isolation), `backend/README.md`
(usage/formulas), root `README.md` (status), `docs/ARCHITECTURE.md` (separate virtual
portfolio branch), and `CODEX_TASK.md` (implementation status).

## Resources, limitations and deferred work

Each invocation creates fresh ledger, dedupe and replay state. Existing
HistoricalReplay owns its feature task/subscription; aclosing ensures cancellation,
error and normal completion clean up. No extra application task, HTTP endpoint or
network integration is added. Exceptions invalidate a mutable ledger; it cannot
resume or finalize partially failed transitions.

Input grouping uses O(symbols) plus one frame; feature history stays bounded.
Active positions/reservations are bounded by configured capacity and one per
symbol. Horizon evidence is hashed incrementally, not retained as raw bars.
Finite audit records/dedupe are O(decisions/positions), and curve storage is
O(timestamps*symbols) because each state retains symbol exposure. The full report
is intentionally retained for review; arbitrarily large finite datasets still
need memory/CPU planning. No duplicate full raw or feature/strategy dataset is kept.

Limitations: bar availability/zero latency; missing liquidity, spread, market
impact, intrabar extremes, funding, taxes and account mechanics; uncalibrated
engineering defaults; passive limit breaches after losses; unknown valuation
after missing data; existing bounded indicator reseeding; and cross-platform
float/libm reproducibility not independently qualified. These artifacts do not
authenticate externally supplied decisions and do not imply achievable fills,
exchange solvency/liquidation behavior or future profitability.

Deferred: Sharpe/Sortino and annualization, portfolio time segments, file loaders/
downloads, durable audit/database, real quantity/lot sizing, dynamic exits,
stop/target orders, exchange-accurate funding/margin/liquidation, private/account
integration, credentials, real/testnet execution, intent generation, pre-execution
risk wiring, P2P, AI/ML/RL, optimization and production portfolio orchestration.
No such integration or Phase 8 work was introduced. No mandatory Phase 7 feature
is intentionally deferred.
