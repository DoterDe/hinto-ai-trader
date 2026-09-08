# Phase 3 completion report

Branch: `phase-3-feature-engine`. Work continued from the existing Batch 1 and
partial Batch 2 working tree. No changes were discarded, and no commit or push
was performed. The initial tree was clean and the complete accepted baseline was
**675 passed, 2 warnings in 1.82s** using the backend virtual environment.

Final verification on 2026-09-09: **1106 passed, 2 warnings in 2.72s** from
`python -m pytest`: all 675 original tests plus 431 Phase 3 tests. Phase 3 is
complete; no later phase was started. Final dependency, import/OpenAPI, offline
lifecycle, scope, and whitespace checks passed.

## Scope and architecture

The implemented flow is `MarketDataHub -> FeatureEngine -> FeatureSnapshot`.
Snapshots are deterministic immutable numerical observations for future strategy
consumers. No strategy scoring, direction/action labels, SignalCandidate creation,
AI, account/private data, API keys, execution, database, or book reconstruction
was added. Phase 1 code and existing Phase 1/2 tests were preserved.

The domain owns typed feature values, availability, source timestamps, and status.
Pure indicators are separate from bounded history and lifecycle orchestration.
The small additional `feature_calculations.py` module assembles values so that
the consumer does not mix formulas with queue/freshness control. Typed settings
live in the application layer and add no runtime dependency.

Each feature group is atomic: all its numerical components must be defined before
its values become available. Groups expose `ready`, `warming_up`, `stale`, or
`unavailable`, sample counts, and reasons. Snapshot readiness is `ready` if all
groups are ready, `partial` if only some are ready, otherwise `stale` takes
precedence over `warming_up`, then `unavailable`. Sources report event/receive
timestamps, connection identity/generation, and freshness reasons. The latest
closed-candle timestamp and history-reset diagnostics are separate from the
current open-kline source timestamp.

## Defaults and formulas

Environment settings use `FEATURE_` with suffixes below. Integer windows must be
positive, EMA fast < slow < long, volatility needs at least two returns, rolling
return windows are nonempty/unique/increasing, and history capacity must satisfy
every window including predecessor candles.

| Setting | Default |
| --- | --- |
| EMA_FAST / EMA_SLOW / EMA_LONG | 9 / 21 / 50 |
| RSI_PERIOD / ATR_PERIOD / ROC_PERIOD | 14 / 14 / 10 |
| VOLATILITY_WINDOW | 20 |
| RELATIVE_VOLUME_WINDOW | 20 |
| VWAP_WINDOW | 20 |
| ROLLING_RETURN_WINDOWS | `[5, 10, 20]` |
| HISTORY_LIMIT | 500 |

In the formulas, C is closed price, V is reported base volume, Q is reported quote
volume, and B is reported taker-buy base volume. Returns are fractions except
explicit percentage/bps fields.

| Group | Formulas | Default closed-candle warmup |
| --- | --- | --- |
| Trade | Latest normalized trade price and quantity | One fresh trade |
| Returns | `(C[t]-C[t-1])/C[t-1]`; `ln(C[t]/C[t-1])`; `(C[t]-C[t-N])/C[t-N]` for configured N | 21 |
| Trend | SMA seed over N prices, then EMA alpha `2/(N+1)`; signed fast-slow and slow-long spreads; `(C-EMA)/EMA` distances | 50 |
| Momentum | Wilder RSI, SMA seed over N changes then alpha `1/N`; ROC `100*(C[t]-C[t-N])/C[t-N]`; `C[t]-C[t-1]` | 15 |
| Volatility | TR `max(H-L, abs(H-prevC), abs(L-prevC))`, first TR `H-L`; ATR SMA seed over N TRs then Wilder alpha `1/N`; ATR/C, 100*ATR/C; sample standard deviation of last 20 log returns, not annualized | 21 |
| Volume | Last 20 candles `sum(Q)/sum(V)`; latest V / mean of preceding 20 V; latest B/V; latest candle delta proxy `2*B-V` | 21 |
| Microstructure | Bid, ask, midpoint `(bid+ask)/2`, spread `ask-bid`, spread/midpoint*10000, quantities, `(bidQty-askQty)/(bidQty+askQty)` | One fresh BookTicker |
| Mark/funding | Mark/index; signed basis `mark-index`, basis/index*100 and *10000; funding rate; signed seconds `(nextFunding-generatedAt)` | One fresh MarkPrice |
| Regime inputs | ATR/C, `(EMAfast-EMAslow)/EMAslow`, `abs(C[t]-C[t-N])/sum(abs(close changes))` over ROC_PERIOD, relative volume | 21 |

RSI is explicitly 100 for gain-only, 0 for loss-only, and 50 for flat histories.
A flat efficiency path is undefined, so the regime group is unavailable. Crossed
books, zero combined top quantity, invalid log inputs, zero volume denominators,
and invalid/nonfinite arithmetic produce unavailable groups, not invented zeros.
Zero volatility and zero signed price change are valid when mathematically defined.
A negative funding countdown means the reported timestamp has passed; it is not
clamped and is not an execution trigger.

VWAP uses the normalized candle's reported quote/base volumes, not a typical-price
approximation. The taker delta proxy describes only that candle's available base
volume split. It does not claim exchange-wide true flow, unseen trades, or book
liquidity. No depth-derived feature is produced: normalized deltas cannot establish
a reconciled full book or full-book imbalance.

Decimal calculations use a fixed precision of 34 independent of caller context.
Overflow, inexact underflow, invalid division, and nonfinite outputs become unavailable.
Log-return statistics use finite floats after guarded Decimal logarithms; prices,
volumes, EMAs, ratios, and funding rates remain Decimal. JSON preserves them as
strings, with no NaN/Infinity constants. Numerical tests use independent expected
values and include extreme magnitudes and ambient Decimal context changes.

## History and freshness

History holds at most HISTORY_LIMIT closed normalized candles per symbol. These
stores isolate candle updates, gaps, revisions, and evictions; a shared-connection
or subscriber-loss reset deliberately affects all configured symbols.
The engine selects the Hub's first configured kline interval unless explicitly given
another configured interval; the existing feed configuration selects one interval.
UTC stepping supports seconds through weeks and real calendar months. A closed
flag is accepted only after the expected interval end; inclusive or exclusive
closing timestamps are tolerated within the interval. Open candles never enter
historical indicator calculations.

Identical duplicates and older events cannot extend history. Conflicting finalized
revisions, overlapping windows, missing closes, and invalid OHLC/taker-volume data
invalidate continuity. No gaps are filled. Eviction removes the oldest candle.
EMA/RSI/ATR are recalculated with seeds from retained history; this intentionally
differs from infinite-history recursion after eviction. There is no persistence
or historical REST preload.

| Feature groups | Required fresh stream | Loss tolerance |
| --- | --- | --- |
| Trade | Trade | Current Hub value suffices |
| Returns, trend, momentum, volatility, volume, regime | Selected Kline | Enough contiguous closed history required |
| Microstructure | BookTicker | Current Hub value suffices |
| Mark/funding | MarkPrice | Current Hub value suffices |
| Full-depth features | None implemented | Deferred until reconciled snapshots exist |

An unrelated stale/missing stream does not invalidate another group's values.
Freshness checks both exchange and receipt age, connection health, generation,
and clock skew using Hub per-stream metadata. A fresh current open kline permits
use of recent closed history; its close is expected by the next interval boundary
plus the Hub stale threshold (10 seconds by default). Repeated obsolete open
updates cannot keep old history ready indefinitely. Reads recompute freshness and
drain queued observations, including continuity checks, before serving a snapshot.

Two small Hub compatibility changes were required:

1. `subscribe()` returns an asyncio.Queue subclass exposing a read-only
   `dropped_events` count for that subscriber; existing queue behavior and aggregate
   status counts remain compatible.
2. Future-clock diagnostic observations remain cached and visibly stale but are
   not queued. A delayed consumer cannot rehabilitate them when time catches up.

The engine uses a bounded 1,000-entry subscription. Its own overflow, candle
connection identity/generation/status changes, and local clock rollback clear
history, discard pending observations, and seed at most one fresh closed candle
from the current Hub cache. This establishes provenance without guessing the
generation of queued timestamps. Other subscribers' overflow and unrelated
book/depth reconnects do not reset candle history. Initial bursts before the
consumer sees connection setup may therefore contribute at most one seed.

Reconnection and planned WebSocket rotation require rewarming. With default 1m
candles, the trend group needs 50 observed closed candles after a reset; other
groups become available according to their own windows. Book/trade/mark context
recovers as soon as each required stream is fresh.

## Lifecycle and API

The app factory accepts an optional third `feature_settings` argument. Import
creates no feed or feature runtime. Lifespan instantiates a new Hub and engine,
registers the consumer before an enabled/injected source starts publishing,
and cancels/awaits the feed and feature tasks on shutdown. Disabled external data
without an injected source creates no feature task/subscription. Cancellation and
failure remove subscriptions and clear history. Unexpected consumer failure is
reported as `engine_failed` without exception text.

- `GET /features/status`: running state, interval, capacity, per-symbol/group readiness.
- `GET /features/{symbol}/latest`: typed values, source timestamps, reasons, and history diagnostics.
- Unknown symbol: sanitized 404. Before initialization: 503. Mutation methods: 405.

All feed/consumer/API operations belong to one event loop. Instantaneous groups
read current Hub observations; snapshots compute current availability at read
time so quiet periods expire without a periodic timer.

## Files created

- `backend/src/domain/features.py`
- `backend/src/application/feature_settings.py`
- `backend/src/application/feature_history.py`
- `backend/src/application/feature_calculations.py`
- `backend/src/application/feature_engine.py`
- `backend/src/indicators/__init__.py`
- `backend/src/indicators/_numeric.py`
- `backend/src/indicators/trend.py`
- `backend/src/indicators/momentum.py`
- `backend/src/indicators/volatility.py`
- `backend/src/indicators/volume.py`
- `backend/src/indicators/microstructure.py`
- `backend/src/api/features.py`
- `backend/tests/test_feature_models_settings.py`
- `backend/tests/test_indicators_trend_momentum.py`
- `backend/tests/test_indicators_context.py`
- `backend/tests/test_feature_history.py`
- `backend/tests/test_feature_calculations.py`
- `backend/tests/test_feature_subscription.py`
- `backend/tests/test_feature_engine.py`
- `backend/tests/test_feature_edge_cases.py`
- `backend/tests/test_feature_api.py`
- `docs/PHASE_3_REPORT.md`

## Files modified

- `backend/src/application/market_data_hub.py`: subscriber-local loss and diagnostic filtering.
- `backend/src/main.py`: feature runtime lifecycle and router.
- `backend/tests/conftest.py`: isolate FEATURE_ environment overrides in tests.
- `backend/README.md`: feature contracts, configuration, formulas, and operations.
- `docs/ARCHITECTURE.md`: implemented Phase 3 boundary and compatibility decisions.
- `README.md`: project status and numerical feature scope.
- `CODEX_TASK.md`: completion status; original task retained.

## Validation

Commands ran in `backend` with `.venv/Scripts/python.exe`, the repository's
Python 3.11.9 environment. Tests are offline; source, transport, and clock
fixtures avoid live Binance dependency.

| Check / command after `python -m pytest` | Exact result |
| --- | --- |
| Baseline complete suite | 675 passed, 2 warnings in 1.82s |
| `tests/test_feature_models_settings.py` | 85 passed in 0.27s |
| `tests/test_indicators_trend_momentum.py -q` | 94 passed in 0.15s |
| `tests/test_indicators_context.py -q` | 71 passed in 0.22s |
| Batch 1: all three above | 250 passed in 0.44s |
| Resumed interrupted `tests/test_feature_history.py` | 6 failed, 57 passed in 0.38s; fixed below |
| History after resumed fixes | 67 passed in 0.25s |
| History including overlap review fix | 69 passed in 0.24s |
| `tests/test_feature_calculations.py -q` | 40 passed in 0.28s |
| Hub + calculation compatibility | 113 passed in 0.33s |
| Initial engine integration | 23 failed, 11 passed in 1.58s; typed generic fix applied |
| Expanded engine integration | 40 passed in 0.44s |
| Batch 3: engine, edge cases, calculations, history, subscription, existing Hub tests | 231 passed in 0.77s |
| Batch 4: feature API + existing market API + existing health/config API | 51 passed, 2 warnings in 1.18s |
| Final complete suite: `python -m pytest` | 1106 passed, 2 warnings in 2.72s |

The interrupted history tests still expected pre-review revision handling and
contained an outdated interval-boundary expectation; these were aligned with
explicit conservative reset semantics. Malformed copied models now safely reset
history. Initial integration also exposed unspecialized Pydantic generic groups;
the engine now constructs the concrete typed group declared by FeatureSnapshot.
All identified failures were corrected before proceeding.

Additional commands/checks:

- `python -m pip check`: `No broken requirements found.`
- Import/OpenAPI: six application paths; feature runtime absent at import.
- Offline injected-source lifespan smoke: both tasks stopped, zero subscribers.
- `git diff --check`: passed, no whitespace errors.
- `git status` / `git diff --stat`: reviewed on `phase-3-feature-engine`;
  7 modified tracked files and 23 new untracked files. Nothing staged, committed,
  or pushed. Standard diff statistics exclude the untracked files.
- Added-content credential-pattern scan: no matches. Import/endpoint/action/TODO
  scan and read-only review found no prohibited Phase 3 integration, accidental
  file type, unbounded feature history, or unguarded NaN/Infinity response path.
  Only `conftest.py` changed among existing test files; all original test modules
  remain intact.

The final checks used the same repository virtual environment as the suite.
Import/OpenAPI confirmed six read-only application paths and no feature runtime
at import. The offline injected-source smoke confirmed both tasks stopped and
zero subscribers after shutdown. No production code changed during Batch 5.

## Deferred work and technical risks

All features in the Phase 3 scope are implemented. Deliberately deferred: strategy
scoring/labels, AI, execution/private/account integration, persistent/distributed
state, REST backfill, depth snapshots/reconciliation, and full-book features.

Remaining operating limits:

- State is process-local and lost on restart; use one API worker.
- Every reconnect/rotation or observed queue gap can require up to 50 default
  closed candles to rewarm the trend group. No historical backfill reduces this wait.
- Bounded reseeding differs from infinite-history EMA/RSI/ATR after eviction.
- Groups are atomic; an undefined component such as a volume ratio can hide other
  otherwise computable fields within that group, with an explicit unavailable state.
- Source continuity cannot be proven for losses never observable through candle
  boundaries, connection changes, or queue counters. No reconstructed book is claimed.
- Sustained live throughput and long-running feed behavior are not qualified by
  offline tests. Reads recompute bounded indicators; high-frequency polling and
  heavy publication can cause conservative queue resets. Runtime skips full Hub
  synchronization for non-candle observations to reduce avoidable work.
- Two existing dependency deprecations remain: Starlette's httpx TestClient path
  and the AnyIO BlockingPortal compatibility alias. No dependency change was made.
- Windows Git may report LF-to-CRLF conversion notices; these are not test failures.
