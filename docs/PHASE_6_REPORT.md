# Phase 6 completion report — Deterministic Backtesting & Validation

Branch: `phase-6-backtesting`. Phase 6 adds an offline application service for
signal-level validation. All Phase 1–5 production engines, settings defaults,
HTTP routes and lifespan behavior are preserved. No dependency, execution path,
optimizer or Phase 7 work is introduced. Changes remain uncommitted and unpushed.

## Validation evidence

The original working tree was clean. The accepted baseline, run with the
repository virtual environment from `backend`, was:

```text
python -m pytest
1645 passed, 2 warnings in 5.74s
```

Targeted batch results, in implementation order:

| Validation | Exact result |
| --- | --- |
| Batch 1: contracts/settings/math | 158 passed in 0.42s |
| Batch 2: replay/decision capture plus Batch 1 | 169 passed in 3.03s |
| Batch 3: evaluator plus earlier batches | 191 passed in 3.17s |
| Batch 4: metrics plus earlier batches | 212 passed in 3.31s |
| Initial end-to-end/longer replay validation | 222 passed in 15.74s |
| Final boundary checks: metrics/evaluator/contracts | 163 passed in 0.56s |
| Final complete Phase 6 targeted selection | 228 passed in 15.83s |

The exact targeted commands were:

```text
python -m pytest tests/test_backtest_contracts.py tests/test_backtest_math.py
python -m pytest tests/test_historical_replay.py tests/test_backtest_contracts.py tests/test_backtest_math.py
python -m pytest tests/test_backtest_evaluator.py tests/test_backtest_math.py tests/test_backtest_contracts.py tests/test_historical_replay.py
python -m pytest tests/test_backtest_metrics.py tests/test_backtest_evaluator.py tests/test_backtest_math.py tests/test_backtest_contracts.py tests/test_historical_replay.py
python -m pytest tests/test_backtest_engine.py tests/test_backtest_metrics.py tests/test_backtest_evaluator.py tests/test_backtest_math.py tests/test_backtest_contracts.py tests/test_historical_replay.py
python -m pytest tests/test_backtest_metrics.py tests/test_backtest_evaluator.py tests/test_backtest_contracts.py
python -m pytest tests/test_backtest_engine.py tests/test_backtest_metrics.py tests/test_backtest_evaluator.py tests/test_backtest_math.py tests/test_backtest_contracts.py tests/test_historical_replay.py
```

The first Batch 2 attempt had **2 failed, 167 passed in 3.64s**: a synthetic
fixture incorrectly expected eligibility despite insufficient production
confidence/agreement. Only the fixture was corrected to a symmetric oscillation
followed by a rise, exercising a known indicator-window transition. Production
strategy/decision rules and thresholds were not changed or fitted to returns.
The next run passed, as recorded above; no failure was hidden or test weakened.

The final targeted selection comprises 116 contract tests, 44 math tests,
11 replay tests, 24 evaluator tests, 23 metrics tests and 10 integration tests.
It includes exact independent LONG/SHORT cost examples, malformed/nonfinite data,
historical freshness versus later stale reads, no-look-ahead prefix invariance,
gap recovery, equal-time symbol ordering, deduplication, exact one/five/calendar
month horizons, incomplete tails, excursions, overlapping signals, independent
metrics and segment censoring. A 650-bar single-pass replay verifies 650 decisions
and the unchanged 500-candle default history bound. Cancellation and input-error
tests verify removal of the feature task and Hub subscription.

The final complete regression used `.venv/Scripts/python.exe -m pytest` from
`backend` (Python 3.11.9, pytest 8.4.2, Windows):

```text
collected 1873 items
1873 passed, 2 warnings in 20.99s
```

This is all **1645 baseline + 228 Phase 6 tests**, with no failures or skips.
Only documentation was edited after that run; production and test files stayed
unchanged. Final ancillary checks used the same repository virtual environment:

| Check | Exact result |
| --- | --- |
| `python -m pip check` | `No broken requirements found.`; exit 0 |
| Inline application import/OpenAPI validation | PASS: 10 unchanged GET paths; finite JSON; zero network calls/import tasks; empty runtime state |
| Inline offline lifespan, feed disabled | PASS: all 10 GET responses 200; paper defaults; NO_ACTION/unavailable; zero remaining tasks/subscribers |
| Inline offline lifespan, injected offline source | PASS: all 10 GET responses 200; source and feature task stop; zero remaining tasks/subscribers |
| Lifespan network guard | PASS: zero connection attempts |
| Inline deterministic historical replay twice | PASS: decisions, outcomes, IDs and all report bytes identical; zero remaining tasks/network attempts |
| Final source/scope audit | PASS: 17 expected new files, 5 expected modified files, no staged files; no existing production/dependency changes |
| AST/numeric/secret/whitespace audit | PASS: valid Python; frozen, finite, revalidated contracts; no credential markers/forbidden integration imports or calls; new-file whitespace clean |
| `git diff --check` | PASS: no whitespace errors |

The inline checks were run via PowerShell here-strings piped to
`.venv/Scripts/python.exe -`; they created no repository helper files. Network
connection functions were guarded during import, lifespan and repeated replay.
Windows event-loop initialization preceded lifespan/replay guards because its
internal socket pair is part of asyncio initialization, not an exchange call.

The two deterministic runs used 80 synthetic minute bars and fixed default
Feature/Strategy/Decision/BacktestSettings. Both produced 80 decisions:
4 ELIGIBLE, 0 BLOCKED, 76 NO_ACTION; 4 completed and 0 incomplete outcomes.
The serialized report was 129409 bytes in both runs:

```text
run_id: backtest_run_c91df6f6adfce42a0f72e16a979733e90636b06afee7e90aaca407a521c108b7
report_sha256: f318e9d938da5645b7265439e208b930e0d448be4e3a3d2f4e725ec266dd937b
```

The separate report SHA-256 is validation evidence, not an additional model
field. An initial standalone-check attempt was rejected because the automatic
approval review model was at capacity. After confirming its offline scope, the
same command passed through the normal approval path and completed successfully.
There is no unresolved approval or validation blocker.

Warnings are the two existing dependency deprecations: Starlette TestClient's
`httpx` integration (suggesting `httpx2`) and AnyIO's `anyio.abc.BlockingPortal`
alias (moving to `anyio.from_thread.BlockingPortal`). Dependencies were not
changed in this phase. Git also prints LF-to-CRLF normalization notices for the
five modified tracked files; these are separate from the two pytest warnings.

## Files

Created production files:

- `backend/src/domain/backtesting.py` — immutable outcome, metric and report contracts.
- `backend/src/application/backtest_settings.py` — validated fixed simulation settings.
- `backend/src/application/backtest_math.py` — pure directional costs and returns.
- `backend/src/application/historical_bars.py` — strict normalized input and ordering.
- `backend/src/application/backtest_identity.py` — incremental dataset and outcome IDs.
- `backend/src/application/historical_replay.py` — historical clock, production replay and capture.
- `backend/src/application/backtest_evaluator.py` — incremental independent fixed horizons.
- `backend/src/application/backtest_metrics.py` — pure aggregate/cohort/segment metrics.
- `backend/src/application/backtest_engine.py` — finite-run orchestration and report assembly.

Created tests/documentation:

- `backend/tests/backtest_fixtures.py`
- `backend/tests/test_backtest_contracts.py`
- `backend/tests/test_backtest_math.py`
- `backend/tests/test_historical_replay.py`
- `backend/tests/test_backtest_evaluator.py`
- `backend/tests/test_backtest_metrics.py`
- `backend/tests/test_backtest_engine.py`
- `docs/PHASE_6_REPORT.md`

Modified existing files:

- `backend/tests/conftest.py` — clear `BACKTEST_` overrides in the existing offline test fixture.
- `backend/README.md` — offline usage, input/rule/formula/resource documentation.
- `README.md` — Phase 6 status and offline branch.
- `docs/ARCHITECTURE.md` — replay/evaluation boundaries and lifecycle.
- `CODEX_TASK.md` — implementation status; original task requirements retained.

No existing production Python file, dependency manifest or previous phase report
was modified. The optional local-file loader and HTTP API were deliberately omitted.

## Historical input contract

Input is a finite iterable of existing immutable `KlineEvent` objects, with an
explicit symbol set and one interval. Required fields remain symbol, interval,
open/close/event/receipt times, OHLC, base/quote volumes, taker-buy base/quote
volumes, trade count and `is_closed=True`. Prices/volumes use Decimal.

All timestamps must be actual aware datetimes. Open times align to a UTC interval
grid. Fixed units anchor to 1970-01-01, weeks to Monday 1970-01-05, and calendar
months to January 1970 with real month lengths. Event and receipt times equal
the exclusive interval end by explicit historical availability convention.
Close time may be that end or end minus 1 ms; both normalize to the same UTC end.
This is a local replay contract, not a claim about Binance publication latency.

Validation rejects nonpositive/nonfinite prices, inconsistent OHLC/high/low,
negative volumes, taker volumes exceeding totals, nonzero quote volume with zero
base volume, open candles, naive/numeric or inconsistent times, malformed model
copies, duplicate/overlapping/misaligned bars, older event times, and scope
mismatches. Zero-volume bars are allowed without inventing flow. Missing bars
remain missing; no interpolation or forward-fill occurs.

Input must have nondecreasing event times. Equal-time groups sort lexically by
symbol, giving `(event_time, symbol)` ordering independent of equal-time input
order. At most one next-time record is read to close a group. Configured symbols
are supplied before replay, never inferred from future data.

## Architecture, clock and no-look-ahead

```text
finite finalized KlineEvent iterator
  -> strict ordering / ReplayClock / MarketDataHub
  -> unchanged FeatureEngine -> FeatureSnapshot
  -> unchanged StrategyEngine -> StrategySnapshot
  -> unchanged DecisionEngine -> HistoricalDecision / DecisionRecord
  -> independent BacktestEvaluator -> hypothetical outcomes
  -> pure metrics / cohorts / chronological segments -> BacktestRunReport
```

Replay registers one existing FeatureEngine consumer and marks the historical
kline source connected. Each step advances an injected monotonic clock to that
bar's end, publishes only that bar, and uses FeatureEngine's public `latest()`
to drain the queue before reading. StrategyEngine and DecisionEngine receive the
same explicit historical time. No `datetime.now()` is used for replay correctness,
no freshness default is weakened and no historical-gap sleep occurs.

Bar t+1 data can only reach the analytical pipeline on the following step. The
ordering iterator's read-ahead never publishes future data. Tests change future
prices and compare every earlier decision, and separately inspect Hub publication
order. Outcome evaluation uses subsequent bars only after the originating decision
exists; evaluated returns never feed features, strategies or policy settings.

Production warm-up, bounded-history reseeding and gap/continuity invalidation are
preserved. A gap resets the candle history and rewarms the indicators. Missing
trade, book, depth and mark observations stay unavailable; the existing optional
book confidence penalty remains. Historical snapshots pass at replay time and
become stale under the existing later-time checks. This bar-only source does not
simulate public-feed reconnects, network latency or intrabar observations.

## Entry, horizon, completeness and identity

A decision from finalized bar t enters at **open(t+1)** and exits at
**close(t+H)**, default H=5. H=1 enters and exits within the next complete bar.
For minute bars, a source `[00:00,00:01)` enters the next bar at 00:01 and, with
H=5, exits at 00:06. The source close and next open have the same boundary timestamp,
but the entry price is the next bar's open. This assumes bar-end availability and
zero processing latency; it does not model an achievable exchange fill.

Every expected bar t+1 through t+H must exist. A later bar cannot shift the
horizon past a gap. `missing_entry_bar`, `missing_horizon_bar`, and `dataset_ended`
produce INCOMPLETE outcomes. Known entry time/price can remain, but no exit,
returns, costs or excursions are fabricated. Completed records use
`horizon_completed`. Only unique ELIGIBLE decisions produce outcomes; BLOCKED
and NO_ACTION remain counted diagnostic records. Overlapping horizons are
independent signals with no capital allocation or active-position limit.

DecisionCapture uses the unchanged Phase 5 decision ID and a stable analytical
fingerprint. Repeated equivalent reads are suppressed and counted; conflicting
reuse of an ID fails. Read-time timestamps, readiness/reasons and full snapshot
identity are excluded from the fingerprint where upstream identity permits them
to vary. The evaluator samples exactly at the associated source bar's end and
requires that current-bar association. Deduplication is finite and run-local,
not persistent action suppression.

Dataset IDs incrementally hash canonical normalized bars and schema version in
replay order. Equivalent timezone/close-boundary/Decimal representations hash
consistently. Outcome IDs hash the decision ID, backtest settings ID, source bar,
observed horizon evidence, status/reason and backtest version. Missing future
evidence is never fabricated. Run IDs combine dataset identity, feature/strategy/
decision/backtest settings identities, symbol/interval scope and engine versions.
No random UUID or wall-clock run metadata is used. `metadata.run_id` identifies
the report; there is no separate `report_id` field. Full serialized report equality
is checked, alongside decision and outcome IDs. Keep supplied configurations and
the code revision with reports: metadata stores configuration hashes, not copies.

## Cost and excursion formulas

Defaults: H=5; fee=5 bps per side; adverse slippage=2 bps per side; four reporting
segments. `BACKTEST_` environment settings are supported without automatically
loading `.env`. H is a positive integer, segments an integer in [1,100], fee a
finite nonnegative Decimal, and slippage finite in [0,10000) bps to retain positive
effective prices. These are engineering assumptions, not verified exchange fees.

Let E be raw next-open entry, X raw horizon-close exit, d=+1 for LONG or -1 for
SHORT, s=slippage_bps/10000 and f=fee_bps/10000:

```text
effective_entry E' = E * (1 + d*s)
effective_exit  X' = X * (1 - d*s)
gross_return      = d * (X-E) / E
slippage_cost     = s * (1 + X/E)
fee_cost          = f * (E' + X') / E
total_cost        = slippage_cost + fee_cost
net_return        = gross_return - total_cost
```

All returns divide by raw E; there is no quantity, account or leverage. Fees
apply to both effective prices. LONG slippage raises entry and lowers exit;
SHORT slippage lowers sale entry and raises buyback exit. Gross return, both cost
components, total cost and net return are distinct fields in `outcome.returns`.
The independently tested default LONG E=100, X=110 example has gross 0.1,
slippage cost 0.00042, fee 0.00104999 and net 0.09853001. The SHORT E=100, X=90
example has net 0.09867001. These are arithmetic fixtures, not performance claims.

Over highs h and lows l of t+1 through t+H only:

```text
LONG:  MFE=max(0,(max(h)-E)/E); MAE=min(0,(min(l)-E)/E)
SHORT: MFE=max(0,(E-min(l))/E); MAE=min(0,(E-max(h))/E)
```

MFE is nonnegative, MAE nonpositive. They exclude costs, the decision bar and
post-exit bars; no intrabar path or hypothetical stop/target order is inferred.
Backtest arithmetic uses its own 34-digit Decimal context, restoring the caller's
context. Overflow, underflow, invalid arithmetic, nonfinite values and zero entry
denominators fail closed. Undefined metrics use null, never NaN or Infinity.

## Metrics and reporting

Input count is in metadata. Decision counts reconcile as evaluated=eligible+
blocked+no_action; eligible=completed+incomplete=LONG+SHORT. Direction counts
include incomplete eligible outcomes. Every eligible decision must have exactly
one explicitly completed or incomplete outcome before metric calculation;
duplicates, mismatched provenance and noneligible outcomes fail validation.

Completed outcomes sort by `(exit_time, decision_time, symbol, decision_id)`.
For N completed signals with net returns r, gross returns g and costs c:

| Metric | Definition |
| --- | --- |
| Win/loss/flat | r>0 / r<0 / r=0 exactly, after costs |
| Win rate | wins/(wins+losses); flats excluded; null at zero denominator |
| Mean gross | sum(g)/N; null if N=0 |
| Mean net / expectancy | sum(r)/N, including flats; null if N=0 |
| Median net | Middle sorted r, or mean of two middle values; null if N=0 |
| Gross/cost/net sums | sum(g), sum(c), sum(r), respectively; zero when empty |
| Gross profit | Sum of positive **net** r; distinct from pre-cost gross-return sum |
| Gross loss | Absolute magnitude of summed negative **net** r |
| Profit factor | gross_profit/gross_loss when loss>0; loss-only gives zero |
| Zero-loss profit factor | null plus `no_losses`, `no_nonflat_outcomes`, or `no_completed_outcomes` |
| Best/worst | max/min net r; null if N=0 |
| Streaks | Maximum consecutive positive/negative r in exit order; flats break both |
| Normalized curve | C0=1, Ck=1+sum(r1..rk); each point also exposes cumulative net return |
| Drawdown | Pk=max(C0..Ck); DDk=(Pk-Ck)/Pk; maximum DDk reported |

The initial peak is 1, avoiding a zero drawdown denominator. The additive curve
can become negative and drawdown can exceed 100%; neither is clamped. This is
an overlapping signal-return sequence, not compounded capital or account drawdown.
Incomplete/censored outcomes contribute counts, not returns or charged costs.

Cohorts use symbol, direction (including NEUTRAL diagnostics), DecisionOutcome
and the source strategy-coverage flag. The coverage label `not_marked_incomplete`
does not assert that every strategy was ready. Configured symbols with no data
can have empty cohorts. Existing numeric regime inputs are retained on sampled
decisions; no stable regime category exists, so no clustering or new category
is invented. Cohort decisions and outcomes reconcile with their parent records.

N segments split the first source open through the final close into fixed equal
elapsed-time spans at microsecond resolution. Decision ownership is `[start,end)`,
with the final end included. Outcomes score only if their entire nominal horizon
ends by that segment's end. Cross-boundary horizons count as incomplete and
`boundary_censored_count`, regardless of later completion or future prices.
An exit exactly at a segment end is available there. A censored signal is not
reassigned to another segment. Therefore completed/return totals across segments
need not sum to the whole run. Segment boundaries use the supplied full reporting
range; they never affect decisions. This is chronological reporting with fixed
settings, without fitting, training or policy selection.

## Lifecycle, memory and limitations

Each `BacktestEngine.run()` owns fresh replay, dedupe, pending horizon and report
state. One FeatureEngine task/subscription is started for a nonempty replay and
cancelled/awaited on exhaustion, error or cancellation. Empty input creates none.
There are startup/periodic zero-delay cancellation checkpoints, no historical
duration waits or exchange connections. Direct early consumers of `frames()`
must use `aclosing`; the runner does. Existing FastAPI routes/lifespan are unchanged
and no backtest task runs at application startup.

Input is single-pass, with O(symbols) equal-time buffering plus one look-ahead
record. Feature history remains bounded at 500 candles per symbol by default.
Pending state is O(symbols*H) under one-decision-per-bar sampling; horizon evidence
is hashed incrementally, not retained as raw bars. Dedupe and final immutable
decision/outcome/curve artifacts consume O(decisions) memory for a finite run;
the report intentionally retains these records for audit. No unbounded live
queue/history or duplicate full raw/feature/strategy dataset is added. Work
includes production bounded feature calculations per bar, O(H) pending work per
bar and final sorting/cohort/segment scans. Very large finite reports, symbol
sets or configured horizons can still be expensive. The 650-bar test is a sanity
check, not a throughput benchmark or proof for arbitrary dataset sizes.

Intentionally deferred: CSV/NDJSON loader and historical downloader; HTTP backtest
endpoint/CLI; persisted reports; full order-book reconstruction; intrabar replay,
latency, queue priority, liquidity/market impact, funding, taxes, liquidation and
account constraints; portfolio allocation/sizing, TradeIntent/ApprovedTradeIntent
creation, independent RiskEngine approval and any paper/testnet/live execution.
No private/account APIs, credentials, balances/positions, order placement, leverage,
margin, P2P, AI/OpenAI, ML/RL, parameter optimizer or database/Redis was added.

Remaining technical risks are dataset quality and the explicit zero-latency
bar-availability assumption, missing microstructure/funding, existing indicator
reseeding after bounded eviction/gaps, finite-report memory/CPU growth and
cross-environment numerical reproducibility. Repeated runs are verified in the
repository environment; cross-Python/platform float/libm behavior in existing
indicator code is not independently qualified. IDs are reproducibility keys,
not cryptographic authentication of externally supplied decision artifacts.
Historical hypothetical validation does not establish achievable fills or future
profitability. No unfinished mandatory feature is intentionally deferred.

## Final working tree

`git status`:

```text
On branch phase-6-backtesting
Your branch is up to date with 'origin/phase-6-backtesting'.

Changes not staged for commit:
        modified:   CODEX_TASK.md
        modified:   README.md
        modified:   backend/README.md
        modified:   backend/tests/conftest.py
        modified:   docs/ARCHITECTURE.md

Untracked files:
        backend/src/application/backtest_engine.py
        backend/src/application/backtest_evaluator.py
        backend/src/application/backtest_identity.py
        backend/src/application/backtest_math.py
        backend/src/application/backtest_metrics.py
        backend/src/application/backtest_settings.py
        backend/src/application/historical_bars.py
        backend/src/application/historical_replay.py
        backend/src/domain/backtesting.py
        backend/tests/backtest_fixtures.py
        backend/tests/test_backtest_contracts.py
        backend/tests/test_backtest_engine.py
        backend/tests/test_backtest_evaluator.py
        backend/tests/test_backtest_math.py
        backend/tests/test_backtest_metrics.py
        backend/tests/test_historical_replay.py
        docs/PHASE_6_REPORT.md

no changes added to commit
```

`git diff --stat`:

```text
 CODEX_TASK.md             |  11 +++
 README.md                 |  14 +++-
 backend/README.md         | 168 +++++++++++++++++++++++++++++++++++++++++++++-
 backend/tests/conftest.py |   2 +-
 docs/ARCHITECTURE.md      |  66 +++++++++++++++++-
 5 files changed, 256 insertions(+), 5 deletions(-)
```

Ordinary `git diff --stat` excludes the 17 untracked files listed above; those
files remain present and unstaged. No reset, restore, revert, clean, checkout,
commit or push was performed. Final validation found no accidental additions.
