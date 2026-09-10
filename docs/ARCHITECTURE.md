# Architecture

## Design goals

Hinto AI Trader separates market observation, signal generation, AI review, deterministic risk control, and execution simulation so each component can be tested independently.

## Core pipeline

The implemented Phase 5 flow ends at analytical eligibility. Future sizing,
risk and execution orchestration are separate steps and are not connected.

```text
Binance Public Market Data
          |
          v
     MarketDataHub
          |
          v
      FeatureEngine
          |
          v
     FeatureSnapshot
          |
          v
     StrategyEngine
          |
          v
 StrategySnapshot / StrategyCandidate
          |
          v
    DecisionEngine
          |
          v
    DecisionRecord
          |
          v
 (future deterministic sizing / TradeIntent)
          |
          v
      RiskEngine
          |
          v
 ApprovedTradeIntent
          |
          v
 PaperExecutionGateway
          |
          v
   Position / PnL
          |
          v
 FastAPI + WebSocket
          |
          v
     React dashboard
```

AI-assisted review and testnet integration remain future work requiring separate
scope. Advisory AI must never bypass deterministic risk controls.

Phase 6 adds a separate offline validation branch, without connecting execution:

```text
Historical finalized KlineEvent iterator -> ReplayClock / MarketDataHub
    -> existing FeatureEngine -> existing StrategyEngine -> existing DecisionEngine
    -> captured historical decisions -> BacktestEvaluator
    -> hypothetical signal outcomes -> metrics / cohorts / chronological segments
```

## Layer boundaries

### Domain
Pure models and interfaces. No FastAPI, database, Binance SDK, or UI imports.

### Application
Coordinates use-cases: features, strategies, AI decision aggregation, deterministic risk checks, execution routing, reconciliation, and portfolio state.

### Infrastructure
Network clients, persistence, Binance public market data, testnet adapter, AI provider adapters, telemetry.

### API
FastAPI HTTP/WebSocket layer. Converts application state to external schemas.

### Frontend
React/TypeScript Trader Desk. It receives only sanitized application data.

## Safety properties

- `PAPER` is the default mode.
- `LIVE` is intentionally absent from the mode enum in the initial implementation.
- AI cannot call an execution adapter directly.
- Phase 1 gateway execution requires independent `RiskEngine` approval. Phase 7
  historical virtual ledger transitions are separate, non-executable artifacts.
- stale data blocks execution.
- signal IDs are idempotency keys.
- secrets never cross into the frontend.

## Phase 1 implementation

Domain models are immutable Pydantic values with aware timestamps and finite
numeric fields. `TradeIntent` carries confidence in `0..1`; strategy intents
default to `1.0`, while AI-assisted intents require an explicit confidence.
The deterministic risk engine enforces a configurable minimum confidence in
addition to signal age, quantity, execution enablement, and duplicate checks.
It revalidates model instances at its boundary and rejects malformed inputs.

The risk engine keeps immutable in-memory decision records for approvals and
rejections, containing unique decision IDs, signal IDs, timestamps, input and
limit snapshots, and reasons. Approval timestamps use the evaluation clock.
Checking and reserving a signal ID and appending its decision are atomic within
one engine instance.

The paper gateway requires an `ApprovedTradeIntent` and revalidates it before
execution. It records one immutable fill per signal ID: identical retries return
the first fill, and conflicting approved payloads fail. The supplied positive,
finite reference price is the fill price; all recorded executions are `paper`.
Approval records are an internal application contract rather than proof of origin.
Only the risk engine should issue them to the execution gateway.

Phase 1 exposes health and sanitized configuration. `testnet` is
an allowed configuration value; no testnet adapter or HTTP trading endpoint is
implemented. AI provider integration is also deferred.

These stores and idempotency guarantees are per instance and do not survive
restarts or coordinate multiple workers. History is currently unbounded. Durable
audit storage and portfolio limits are required in later phases; the present
scaffold validates signal age but does not verify reference-price freshness or
simulate commissions/slippage.

## Phase 2 implementation

`domain/market_data.py` defines immutable normalized events, Decimal prices and
quantities, aware timestamps, connection state, and the `MarketDataSource` /
`MarketDataSink` protocols. The domain and application do not import Binance or
WebSocket libraries. `application/market_data_hub.py` stores the latest event for
each configured symbol and stream, publishes bounded consumer queues, and computes
freshness separately from socket connectivity.

`infrastructure/binance/stream_router.py` groups all symbols into two combined
connections. Aggregate trades, klines, and mark prices use `/market`; book tickers
and diff-depth use `/public`. `parsers.py` binds combined envelopes to the expected
subscription and validates raw values before emitting domain events. It tolerates
additive exchange fields and rejects a supplied non-USD-M symbol type.
`settings.py` validates public-feed configuration; `public_market_data.py` owns
independent connection lifecycles with timeouts, bounded exponential backoff and
jitter, malformed-message isolation, and proactive rotation before 24 hours.
Built-in WebSocket ping/pong support handles the server heartbeat.

Every successful connection increments a generation. Cached values from an older
generation remain visible but stale until newer observations arrive. Freshness
requires every expected stream to have current event and receipt timestamps and
a connected source. Replayed or out-of-order observations do not refresh the
cache. Clock skew is shown explicitly. Backoff prevents rapid retries after failed
or flapping connections; reopening the combined URL restores subscriptions.
Counters persist across cancellation/restart of the same source. A bounded
reference to the last coherent event keeps future-dated diagnostics from poisoning
ordering. Same-millisecond candle progress is retained. A new connection may
establish a reset sequence-ID baseline only with a later exchange timestamp;
this is not a depth-continuity guarantee.

`api/market_data.py` exposes `/market/status` and `/market/{symbol}/latest` using
normalized response models. The `main.py` app factory/lifespan starts and stops
the feed and supports injected sources for offline tests. Existing health,
configuration, risk, and paper-execution contracts remain intact.

The cache and subscriber queues are bounded, process-local, and owned by one event
loop. Slow subscribers lose their oldest queued observation, with drops counted.
These are observation feeds, not durable logs. Connection gaps are not backfilled.
Depth events retain update IDs and changed levels but are never merged into a book;
REST snapshot reconciliation and continuity guarantees are deferred. Phase 2
does not connect market events to strategies or execution.

Current source contracts and operational limits, including official Binance
documentation links, are documented in `backend/README.md`.

## Phase 3 implementation

The implemented observation flow is `MarketDataHub -> FeatureEngine ->
FeatureSnapshot`. Phase 4 consumes that boundary without changing feature code. It has no
dependency on exchange adapters, strategy decisions, AI, risk, or execution.

`domain/features.py` defines immutable typed values and group readiness. Each
group is `ready`, `warming_up`, `stale`, or `unavailable`; unavailable groups have
null values and explicit reasons. A snapshot can be `partial` when some groups
are ready. Trade, candle returns, trend, momentum, volatility, candle volume,
top-of-book context, mark/funding, and numerical regime inputs are separate
groups. Source timestamps, closed-candle timestamps, history size/reset counters,
and per-stream source diagnostics are included. Decimal fields serialize as
strings; log statistics and signed funding countdowns use finite floats.

`application/feature_settings.py` owns validated exchange-independent windows.
`indicators/` contains pure calculations using a fixed 34-digit Decimal context
with overflow/underflow guards. `application/feature_calculations.py` assembles
typed values separately from service lifecycle and availability decisions.
This additional module keeps numerical assembly out of orchestration.

`application/feature_history.py` stores at most 500 closed candles per symbol by
default. The engine selects one of the Hub's intervals (the first by default;
the existing feed config supplies one). Open candles never enter calculations.
UTC interval boundaries, including calendar months, establish continuity without
relying on an exchange-specific inclusive closing timestamp. A closed flag is
insufficient if the expected interval end is still in the future. Duplicates and
older observations cannot extend history. Gaps, overlapping windows, invalid
OHLC/volume, and conflicting finalized revisions invalidate continuity. No bars
are synthesized. EMA/RSI/ATR are reseeded from retained history on calculation;
after eviction they can differ from an indefinitely accumulated recursive series.

`application/feature_engine.py` consumes the Hub on the same event loop. Its
default queue has 1,000 entries. The subscription remains an `asyncio.Queue`,
with an additive per-subscriber `dropped_events` counter. Future-clock diagnostic
events remain stale in Hub snapshots but are not delivered to subscribers; a
delayed consumer must not admit them after time catches up. These are the two
small Phase 2 compatibility changes required for trustworthy feature history.

Queue loss, candle connection identity/generation/status changes, and local clock
rollback clear continuity. Pending observations are discarded and at most one
fresh current-generation closed candle is used as a new seed. This avoids
inferring generation from untagged queued timestamps. Other subscribers' losses
do not reset the engine. Changes on an unrelated book/depth connection do not
reset candle histories. Reconnects and routine connection rotation require fresh
warmup; there is no backfill.

Freshness comes from individual Hub streams, not its overall symbol stale flag:

| Feature groups | Required fresh source | Additional condition |
| --- | --- | --- |
| Trade | Trade | One valid observation |
| Returns, trend, momentum, volatility, volume, regime | Selected Kline interval | Contiguous closed history meeting each group's window |
| Microstructure | BookTicker | Noncrossed prices and nonzero combined top quantity |
| Mark/funding | MarkPrice | Valid basis arithmetic |

A fresh successor open candle can keep the preceding closed history usable.
The next expected candle must close by its interval boundary plus the Hub stale
threshold (10 seconds by default); repeated obsolete open updates cannot extend
that deadline. Reads drain pending observations and recompute freshness, so API
responses expire without a timer or incoming event. Instantaneous trade/book/mark
groups use the current Hub cache and tolerate intermediate observation loss.
Only candle groups require continuity. Undefined numerical components invalidate
their group, including a zero volume denominator or a flat directional-efficiency
path; flat RSI is explicitly 50.

The FastAPI lifespan creates the engine lazily, registers its consumer before
starting an enabled or injected feed, and cancels/awaits both tasks on shutdown.
A disabled network feed without an injected source has no consumer task. Engine
failure exposes the safe `engine_failed` reason and removes its subscription.
`GET /features/status` and `GET /features/{symbol}/latest` expose typed read-only
state; unknown symbols return 404 and requests before initialization return 503.

There are no full-book features: depth deltas cannot prove total liquidity or
book imbalance without snapshots and update-ID reconciliation. The candle taker
volume delta is explicitly a proxy (`2 * taker_buy_base_volume - base_volume`),
not exchange-wide true order flow. Numerical features never generate labels,
signals, approvals, or execution requests. Storage remains bounded, process-local,
nonpersistent, and single-worker. Sustained live throughput is not yet qualified.

Default windows, formulas, warmup counts, validation results, and remaining limits
are recorded in `backend/README.md` and `docs/PHASE_3_REPORT.md`.

## Phase 4 implementation

```text
FeatureSnapshot
    -> independent deterministic strategies
    -> StrategyAssessment (one per enabled strategy)
    -> weighted consensus
    -> optional analytical StrategyCandidate
```

`domain/strategies.py` defines immutable evidence, assessments, candidates,
aggregate snapshots and API status. Scores are Decimal values in `[-100,100]`,
confidence/agreement in `[0,1]`, and timestamps are aware. Evidence carries raw
value, reference, normalized input, weight, multiplier, contribution and code.
The model validates each contribution and the sum represented by a ready score.
Unready assessments carry reasons and null score/confidence, never guessed zeros.
Candidates contain no executable fields and are not Phase 1 `TradeIntent` or
`SignalCandidate` records.

`strategies/scoring.py` supplies bounded piecewise-linear helpers using a fixed
34-digit Decimal context. `strategies/base.py` centralizes feature readiness,
source time checks, evidence assembly and numerical rejection. `identity.py`
provides canonical content hashes. These two supporting modules keep common
validation and identity policy out of the three pure strategy implementations.
`application/strategy_settings.py` centralizes validated thresholds and fixed
component weights. No exchange adapter, FastAPI or execution code is imported by
the strategy modules or the StrategyEngine.

| Strategy | Required groups | Optional confidence context |
| --- | --- | --- |
| Trend following | trend, momentum, regime, volatility | None |
| Momentum continuation | momentum, volume | microstructure spread |
| Mean reversion | trend, momentum, volatility, regime | microstructure spread |

Trend requires corroborated EMA/distance/ROC evidence and scales by efficiency
and ATR. Momentum scales ROC/RSI/change/taker-bias evidence by relative volume and
RSI exhaustion. Mean reversion opposes stretch only with confirming fast-EMA
distance and suppresses conviction in strong trends, high relative volume and
high ATR. All score contributions are exposed; contradictions offset. Candle
taker volume remains a proxy, and depth is never interpreted as a full book.

Hard dependencies inherit per-group unavailable/warming/stale states; multiple
failures prioritize stale, unavailable, then warming. Source timestamps and
generation metadata are checked even when a supplied group claims ready.
Snapshot and source event/receipt age limits default to 10 seconds, with no
future-clock allowance. Sufficient finalized history is required; fresh successor
open-kline observations can maintain its freshness under Phase 3 expiry rules.
Optional absent/stale book context applies a documented quality penalty without
invalidating independent candle evidence. Unrelated stale groups are ignored.

`application/strategy_engine.py` consumes an injected `FeatureProvider.latest`
protocol returning only `FeatureSnapshot`. It preserves individual assessments
and averages scores over READY strategy weights. Aggregate confidence includes
coverage of all configured weights and net/gross directional agreement, so
missing strategies and opposing scores reduce conviction. Any ready strategy
makes the aggregate ready; this means evaluable, not actionable. Inclusive
candidate thresholds default to absolute score 40 and confidence 0.55. Weak or
conflicting results are neutral with no candidate. An individual assessment's
direction uses a separate absolute score threshold of 25.

`evaluate(snapshot)` has no wall-clock dependency unless `now` is supplied.
On-demand `latest/status` reads use an injected clock for live age checks.
Canonical SHA-256 identities distinguish the entire feature snapshot/read from
the relevant analytical observation. Candidate IDs combine engine version,
settings identity, observation identity and direction. API read time and fresh
open-kline heartbeat times alone do not create a new closed-candle observation;
relevant book event times, values, closed time, resets and reconnect provenance do.
No persistent deduplication or action authorization is implied by these hashes.

The app constructs this service lazily during lifespan, after the FeatureEngine
and before starting the existing tasks. It adds no polling loop, consumer queue,
mutable history, cache or task. Existing feed/feature shutdown behavior is unchanged.
`GET /strategies/status` and `GET /strategies/{symbol}/latest` return typed read-only
state, with 404 for unknown symbols and 503 before initialization. No arbitrary
user-feature or execution endpoint is introduced. Each application worker would
still own separate feed/history state; single-worker operation remains intended.

Exact formulas, defaults, confidence/consensus equations, deterministic identity
scope, validation and limitations are in `docs/PHASE_4_REPORT.md` and
`backend/README.md`. There is no profitability claim, AI provider, account access,
order sizing, order execution, strategy-to-risk wiring or additional dependency.

## Phase 5 implementation

`application/decision_engine.py` consumes only the typed
`StrategyProvider.latest(symbol) -> StrategySnapshot` interface. The pure
`evaluate(snapshot, now=...)` requires explicit aware time; `latest/status` use an
injected clock and evaluate on demand. It never calls FeatureEngine, the exchange,
RiskEngine or an execution gateway. Phase 1–4 production services are unchanged;
the app factory adds an optional decision settings argument and lifespan instance.

`domain/decisions.py` defines immutable DecisionRecord, policy, reason and status
models with finite numeric bounds, coherent outcome/value combinations and no
executable fields. `decision_settings.py` exposes four gates: maximum snapshot
age 10 seconds, minimum agreement 0.50, minimum contributors 2 and incomplete
coverage blocking disabled. `DECISION_` process variables override defaults.

`decision_validation.py` revalidates Phase 4 values and checks additional
candidate time/hash/contributor/provenance constraints. No score is recalculated.
Phase 4 still owns candidate score/confidence thresholds and consensus semantics;
confidence is evidence quality, not probability. Contributor count prevents one
rule family from qualifying alone by default, without assuming independent votes.
The candidate contributor set must match READY nonzero assessments supporting its
score sign. Missing-strategy provenance must agree across assessments, snapshot
and candidate; it is retained even when incomplete coverage is allowed.

ELIGIBLE requires READY, fresh, coherent source output and all policy gates.
NO_ACTION means valid fresh output with no candidate, including neutral and
warming/unavailable results. Validation/staleness failures are BLOCKED even if
there is no candidate, keeping unsafe input distinct from ordinary abstention.
Agreement and contributor thresholds are inclusive; age is strictly below its
limit. Both source strategy and feature timestamps are checked independently.
Future time or reversed source ordering fails closed. Candidate time must match
strategy evaluation time. Existing Phase 4 readiness remains authoritative for
individual feature dependencies; Phase 5 does not inspect lower-level data.

Malformed copies yield safe BLOCKED diagnostics when source identifiers are
usable. Untrusted candidate values are omitted and missing source times remain
null. Invalid identifiers or wrong object types are programmer errors in pure
evaluation; an unusable provider becomes a sanitized service/API error.
Valid policy-blocked or stale candidates retain their supplied analytical values.

`decision_identity.py` reuses Phase 4 canonical hashing. Policy identity contains
validated settings and sorted symbol scope; decision identity contains engine
version, policy, symbol, upstream version/settings, observation, candidate (or a
no-candidate marker), and outcome. Read time and full feature snapshot identity
are excluded to preserve identity across equivalent analytical reads. Source IDs
and all evaluation times remain on the record. Changed outcome changes identity.
These are trusted internal content identities, not authentication, persistent
deduplication or unique per-read audit IDs. There is no cache or history.

The app constructs DecisionEngine over StrategyEngine before starting the existing
feed/feature tasks. No task, queue or subscriber is added; cancellation and cleanup
remain unchanged. `GET /decisions/status` exposes policy and symbol summaries;
`GET /decisions/{symbol}/latest` exposes DecisionRecord. Unknown symbols return
404; uninitialized/unusable source state returns sanitized 503; ordinary BLOCKED
and NO_ACTION records return 200. All decision routes are read-only. Import and
OpenAPI generation construct no runtime; status evaluates symbols individually.

ELIGIBLE is not execution approval. Phase 1 TradeIntent needs a concrete quantity,
which Phase 5 does not invent. A future sizing/intent builder and independent
RiskEngine evaluation must precede PaperExecutionGateway. No Phase 1 risk limit
or execution contract is changed, and neither intent type is created here.
No AI, private API, account data, sizing, order submission, database or dependency
is added. No full order book is reconstructed. Exact rules, tests and remaining
limits are in `docs/PHASE_5_REPORT.md` and `backend/README.md`.

## Phase 6 implementation

Historical input reuses KlineEvent. `historical_bars.py` validates finalized OHLCV,
aware times, UTC interval alignment and volume consistency, normalizing supported
close-time conventions to exclusive interval ends. Event/receipt time equal that
end by explicit historical-availability assumption. Ordered input is streamed;
same-time symbols sort lexically with at most one next-time look-ahead record.
Duplicates/unsorted or misaligned input fail, and gaps remain gaps.

`historical_replay.py` injects a monotonic historical clock into MarketDataHub and
the production engines. It registers the existing feature task once and uses its
public synchronous read to drain each published bar before evaluating. No future
bar is published early; no historical-duration sleep or freshness bypass exists.
Gap/continuity resets, warm-up, bounded-history reseeding, strategy thresholds and
decision policy remain unchanged. Missing microstructure/context stays unavailable.
No Phase 1–5 production file is changed.

`backtest_evaluator.py` separately advances pending eligible signals with future
bars. Entry is the next open and exit is close of the Hth following complete bar
(H=5 by default). The default interpretation is independent overlapping signal
outcomes. Missing next/intermediate/exit bars yield INCOMPLETE; no bar or exit is
fabricated. DecisionCapture deduplicates stable IDs and rejects conflicting reuse.
NO_ACTION/BLOCKED records remain diagnostic. MFE/MAE use only the entry-through-exit
window and raw entry normalization, without costs or intrabar path assumptions.

`backtest_math.py` applies adverse LONG/SHORT slippage and effective-price fees
with fixed 34-digit Decimal arithmetic. Defaults are 5 bps fees and 2 bps slippage
per side. Gross, fee/slippage cost and net returns are separately retained, all
normalized to raw entry price. No quantity, portfolio capital or execution service
participates. Exact formulas are in the backend guide and Phase 6 report.

`backtest_metrics.py` calculates independently tested signal counts, expectancy,
win/loss/flat, costs, profit factor, streaks and an additive normalized curve.
The curve starts at 1; drawdown is running-peak-relative and may exceed 100% if
the hypothetical sequence becomes negative. It is not account drawdown.
Symbol/direction/outcome/coverage cohorts retain semantics; numeric regime context
is stored rather than classified. Equal elapsed-time segments censor horizons
extending past their own end. Settings never change between segments and no
training, threshold fitting or optimization occurs.

`backtest_engine.py` owns each finite run, streams replay frames into the evaluator
and assembles immutable domain report models. Dataset identity incrementally hashes
normalized records. Run/outcome IDs include relevant settings, data evidence and
versions. Dedupe and final report records are run-local O(decisions); feature
history remains bounded and pending horizon state is O(symbols*H) for default
one-decision-per-bar sampling. No full raw or feature dataset is retained twice.

Replay cleanup cancels/awaits its feature task and removes its subscription on
completion, error or cancellation. Existing FastAPI import/OpenAPI/lifespan and
its ten routes are unchanged. No loader/downloader, endpoint, database, dependency,
intent builder, RiskEngine approval, gateway call, account API, AI or Phase 7 is
introduced. This measures hypothetical historical signals, with explicit latency,
microstructure and portfolio limitations; it makes no profitability claim.

## Phase 7 implementation

`PaperPortfolioEngine` consumes the unchanged `HistoricalReplay` into complete
same-time groups of immutable bars/decisions. The existing FeatureEngine,
StrategyEngine and DecisionEngine preserve their formulas, freshness and warm-up.
Phase 6 continues to measure independent signals; Phase 7 measures competition
for one shared pool of virtual capital. Neither path feeds returns into strategy
settings or creates an execution request.

`paper_portfolio_policy.py` implements a separate pure policy. Marked equity times
the configured target fraction sets desired virtual notional. Allocation is
all-or-none. Gates check current/known state, positive equity, drawdown, active
symbol, open-plus-reserved count, gross exposure and symbol exposure. Defaults
are 100000 initial units, 0.10 target, 0.40 gross, 0.15 symbol, four positions and
0.20 drawdown. Same-symbol multiplicity is unsupported even if the setting is
explicitly false. Scores/confidence/agreement rank simultaneous decisions, then
symbol and decision ID break ties; confidence does not change notional.

Reservations consume capacity before next-open entry. The ledger applies due
entries, all known close marks/exits, then arbitrates the current timestamp's
decisions. An initial anchor and one canonical close snapshot per timestamp form
the curve. Entry is open(t+1), exit close(t+H), with Phase 6 H/cost settings.
Completed PnL uses Phase 6 `outcome_returns`; open marks subtract entry-side costs
only. Closing removes the unrealized mark and adds complete net PnL once.

Gross exposure adds open and reserved fixed notional without LONG/SHORT netting.
New reservations must fit current marked-equity limits. Passive equity losses may
raise existing exposure fractions beyond limits; no liquidation or forced exit
is invented. Drawdown >= its threshold blocks new reservations until recovery;
existing positions continue their fixed horizons.

An absent next bar expires its reservation. An absent required holding bar makes
that position incomplete and aggregate marked equity unknown permanently. New
reservations fail closed while other existing positions can finish on known bars.
End-of-data reservations expire, and remaining open positions become explicit
incomplete exposure with no final marked equity. Historical curve points retain
their original as-of values rather than being rewritten at dataset end.

Immutable domain artifacts include policy decisions, reservations, expiries,
positions, closes, state/curve points, metrics and reports. Pure metrics reconcile
counts, provenance and realized PnL, reporting known-mark drawdown/exposure maxima,
turnover and symbol/rejection breakdowns. Incomplete valuation and nonpositive
equity are explicit flags. Canonical identities include settings, state and
normalized observed evidence; hashes are not authentication.

The simulator owns finite-run audit history and bounded active exposure/mark
state. Existing 500-candle default history and replay cancellation cleanup remain
unchanged. No existing production code, dependency, HTTP route or app lifespan
task changes. Phase 1 RiskEngine and PaperExecutionGateway remain separate because
they consume executable quantity-bearing intents and have process-local execution
state/identities. Exact formulas and validation are in `docs/PHASE_7_REPORT.md`.

## Phase status and future work

1. Domain + RiskEngine + PaperExecution + FastAPI scaffold.
2. Binance public market data for 8 symbols.
3. FeatureEngine with deterministic numerical snapshots.
4. Deterministic StrategyEngine with analytical assessments and read-only API.
5. Deterministic DecisionEngine with immutable eligibility records and read-only API.
6. Offline deterministic historical replay and signal-level validation reports.
7. Offline deterministic shared-capital virtual portfolio and risk simulation.

Future tasks require separate scope: execution sizing, production portfolio orchestration and persistence,
AIAdvisor interface/provider, React dashboard, testnet adapter/reconciliation,
and additional operational reliability validation. No later phase is started here.
