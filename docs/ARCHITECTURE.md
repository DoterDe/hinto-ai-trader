# Architecture

## Design goals

Hinto AI Trader separates market observation, signal generation, AI review, deterministic risk control, and execution simulation so each component can be tested independently.

## Core pipeline

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
       Strategies
          |
          v
   SignalCandidate
          |
          v
      AIAdvisor
          |
          v
    DecisionEngine
          |
          v
      RiskEngine
          |
          v
 ApprovedTradeIntent
          |
          v
   ExecutionGateway
      |        |
    Paper    Testnet
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
- `RiskEngine` is deterministic and must approve every simulated/testnet action.
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
FeatureSnapshot`. Strategy consumption is a future boundary. Feature code has no
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

## Planned phases

1. Domain + RiskEngine + PaperExecution + FastAPI scaffold.
2. Binance public market data for 8 symbols.
3. FeatureEngine with deterministic numerical snapshots (implemented; strategies deferred).
4. AIAdvisor interface + structured-output provider.
5. Backtesting and persistence.
6. React dashboard.
7. Binance testnet adapter and order reconciliation.
8. Reliability tests: disconnects, stale streams, duplicate events, malformed AI output.
