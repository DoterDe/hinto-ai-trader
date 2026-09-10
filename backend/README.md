# Backend

Phase 1–7 backend for Hinto AI Trader.

## Setup

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run tests

```bash
python -m pytest
```

## Run API

```bash
uvicorn src.main:app --reload
```

Then inspect:

- `GET /health`
- `GET /system/config`
- `GET /market/status`
- `GET /market/BTCUSDT/latest`
- `GET /features/status`
- `GET /features/BTCUSDT/latest`
- `GET /strategies/status`
- `GET /strategies/BTCUSDT/latest`
- `GET /decisions/status`
- `GET /decisions/BTCUSDT/latest`

`/system/config` must report `real_money_execution_enabled: false` in this scaffold.
It defaults to `paper`, accepts `testnet`, and falls back to `paper` for unknown
values (including `live`). `ai_can_bypass_risk_engine` is always `false`.
`TRADING_MODE` is read from the process environment; `.env.example` is a template
and is not automatically loaded.

## Current components

- `src/domain/models.py` — signal, AI decision, trade intent, execution result, trading mode.
- `src/domain/execution.py` — execution gateway interface.
- `src/application/risk_engine.py` — deterministic validation and duplicate protection.
- `src/infrastructure/paper_execution.py` — in-memory simulated fills.
- `src/main.py` — FastAPI entry point.

## Risk and execution contracts

Domain records are immutable. Identifiers must be nonblank, timestamps must be
timezone-aware, and numeric inputs must be finite. Quantities and prices must be
positive. The risk engine and paper gateway revalidate their inputs, including
instances created with Pydantic's validation-bypassing copy/construct helpers.

`RiskLimits` defaults to a 30-second signal age, a maximum quantity of `1.0`,
execution enabled, and a minimum confidence of `0.0`. Confidence must always be
within `0..1`; raise `min_confidence` to require a confidence threshold. Strategy
intents default to confidence `1.0` for compatibility. An `ai_assisted` intent must
explicitly supply confidence. Confidence cannot override age, size, duplicate,
or execution-disabled checks. An AI provider is not connected in Phase 1.

`RiskEngine.decisions` exposes a tuple of immutable approvals and rejections.
Each record includes a decision ID, signal ID, evaluation timestamp, input
snapshot, limits, and reason. Passing `now` makes evaluation and the approval
timestamp reproducible. Concurrent evaluations of the same signal approve once;
rejections do not reserve the signal ID.

Pass the successful decision's `approved_intent` to `PaperExecutionGateway`.
An ordinary `TradeIntent` is rejected. The reference price becomes the simulated
fill price. Retrying the same approved payload returns its original fill, even
if a new valid reference price is supplied. Reusing a signal ID with a different
approved payload raises `ValueError`. Invalid inputs never add fills.

Approvals are internal typed records, not cryptographic authorization tokens.
Application code must obtain them from `RiskEngine`; no HTTP execution endpoint
is exposed. The paper adapter always records mode `paper`, including when the
API configuration reports `testnet`; the testnet adapter is a later phase.

Audit history, duplicate protection, and fills are local to each service instance
and are lost on restart. They are not shared between workers and currently grow
without a retention limit. Use a single instance of each service in a process.
Durable storage, portfolio/notional limits, market-price freshness, slippage,
and commissions remain future work.

## Public market data (Phase 2)

Application startup starts two public Binance USD-M Futures combined WebSocket
connections. The defaults subscribe to BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT,
XRPUSDT, ADAUSDT, DOGEUSDT, and LINKUSDT. One route contains 24 regular market
streams; the other contains 16 book/depth streams. No exchange account is used.

| Stream per lowercase symbol | Route | Frequency |
| --- | --- | --- |
| `@aggTrade` | `/market` | 100 ms aggregation |
| `@kline_1m` | `/market` | 250 ms when updates exist |
| `@markPrice@1s` | `/market` | 1 second |
| `@bookTicker` | `/public` | When best bid/ask changes |
| `@depth` | `/public` | 250 ms default; no `@250ms` suffix |

Each URL has the form
`wss://fstream.binance.com/{route}/stream?streams={stream1}/{stream2}/...`.
The routing and payload contracts were checked against the official Binance
[routing notice](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice),
[market catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market), and
[public catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public)
on 2026-09-06. The ordinary kline builder supports documented minute/hour/day/week/month
intervals and multiple intervals internally; configuration selects one interval.

### Settings

Settings use process environment variables, with the prefix `BINANCE_MARKET_DATA_`.
The complete example is in the root `.env.example`. It is not automatically loaded.

| Suffix | Default | Purpose |
| --- | --- | --- |
| `ENABLED` | `true` | Set `false` for offline startup |
| `SYMBOLS` | The eight symbols above | JSON array; normalized to uppercase |
| `KLINE_INTERVAL` | `1m` | Single candle interval |
| `STALE_AFTER_SECONDS` | `10` | Exchange-event and receipt age threshold |
| `RECONNECT_MIN_DELAY` / `RECONNECT_MAX_DELAY` | `1` / `30` | Bounded exponential retry with jitter |
| `OPEN_TIMEOUT` / `CLOSE_TIMEOUT` | `10` / `5` | Handshake and closing deadlines |
| `RECEIVE_TIMEOUT` | `30` | Maximum route-wide time without usable fresh data |
| `ROTATE_AFTER_SECONDS` | `86100` | Rotate before the 24-hour limit |
| `WEBSOCKET_BASE_URL` | `wss://fstream.binance.com` | Root URL; loopback `ws` supported for tests |

`websockets` is the only additional runtime dependency and is used directly.
It automatically responds to server ping frames with matching pong payloads.
Client-initiated keepalive pings are disabled. Transport buffers, message sizes,
connection/close waits, and reconnect delays are bounded. Each route retries
independently and restores its subscriptions by reopening the same combined URL.
Retry backoff is reset after a session has delivered fresh data and remained
connected for at least `RECEIVE_TIMEOUT`; a handshake alone does not reset it.
The client connects directly, without inheriting system proxy configuration.

### Read-only state and consumers

`/market/status` reports connection states, reconnect generations/attempts,
malformed-message counts, and per-symbol/per-stream freshness. `/market/{symbol}/latest`
adds the latest normalized events. Unknown symbols return 404. Decimal prices,
quantities, and funding rates serialize as JSON strings. No raw payloads or
internal exception text are returned.

Every event includes UTC exchange event time and local receive time. Mark-price
`T` is the next funding time; it is not used to calculate freshness. A symbol is
stale if any expected stream is missing, disconnected, awaiting a new connection's
data, too old, or affected by clock skew. A successful reconnect does not freshen
cached events. Old/duplicate observations cannot refresh receipt timestamps.
The socket's last message time alone is not evidence that all symbols are fresh.
Generation counters also survive cancellation and restart of the same source.
Clock-skewed events remain visibly stale without blocking subsequent coherent
observations. Future-clock observations remain in the diagnostic cache but are
not placed on consumer queues. After a new connection, sequence IDs may restart only when the
exchange timestamp advances; this does not establish depth continuity.

Consumers use `MarketDataHub.subscribe()` as a context manager and await its bounded
queue of normalized events. Slow consumers lose their oldest queued observations;
the aggregate drop count is visible in status, and each queue's `dropped_events`
counts its own losses. Consumers needing continuity must detect gaps using their
own requirements. Hub latest-state memory is bounded by configured symbols/streams;
the Hub stores no historical time series. Phase 3 maintains separate bounded
closed-candle history in `FeatureHistory`.

Depth entries are individual deltas containing update IDs and absolute quantities
at changed levels; zero quantity is a deletion. They are not a complete or
reconciled order book. The hub does not apply or merge depth levels. Public book
feeds also exclude RPI orders. Lossy subscriptions cannot reconstruct an order book.

The feed and API share one event loop. State is process-local and is lost on
restart; multiple API workers would create separate subscriptions and caches.
Reconnect gaps are not backfilled. Use one application worker for this phase.
Market-data freshness is exposed for future deterministic consumers; it is not
wired into Phase 1 execution during this phase.

### Offline tests and startup

All ordinary tests disable external market connections by default. Transport tests
inject sockets, clocks, sleeps, and randomness; API tests inject a normalized data
source. No test depends on Binance being online. Live exchange connectivity and
long-running throughput are separate operational checks.

For an offline server smoke check on PowerShell:

```powershell
$env:BINANCE_MARKET_DATA_ENABLED = 'false'
python -m uvicorn src.main:app --host 127.0.0.1 --port 8765
```

Application import performs no network work. Lifespan startup owns the feed task;
shutdown cancels route tasks, closes sockets, and exposes stopped state. Startup
configuration errors fail validation; an unexpected source failure is reported
with the safe `source_failed` reason.

## FeatureEngine (Phase 3)

`MarketDataHub -> FeatureEngine -> FeatureSnapshot` provides deterministic
numerical observations for future strategies. It generates no trading labels,
scores, signals, AI decisions, intents, or execution requests. Domain and
application code consume normalized events and do not import Binance classes.
Phase 3 adds no runtime dependencies.

The implementation is divided into `src/domain/features.py` for immutable typed
outputs, `src/indicators/` for pure calculations, application-level settings,
history, value assembly and `FeatureEngine`, and `src/api/features.py` for HTTP
reads. Histories and subscriptions belong to one application event loop.

### Feature settings

Process environment overrides use the `FEATURE_` prefix. As with market-data
settings, `.env` files are not automatically loaded. Defaults are:

| Suffix | Default | Meaning |
| --- | --- | --- |
| `EMA_FAST` | `9` | Fast EMA period |
| `EMA_SLOW` | `21` | Slow EMA period |
| `EMA_LONG` | `50` | Long EMA period |
| `RSI_PERIOD` | `14` | Wilder gain/loss smoothing period |
| `ATR_PERIOD` | `14` | Wilder true-range smoothing period |
| `ROC_PERIOD` | `10` | Return and directional-efficiency horizon |
| `VOLATILITY_WINDOW` | `20` | Number of log returns in sample volatility |
| `RELATIVE_VOLUME_WINDOW` | `20` | Preceding closed candles forming the volume baseline |
| `VWAP_WINDOW` | `20` | Closed candles in rolling VWAP |
| `ROLLING_RETURN_WINDOWS` | `[5,10,20]` | JSON array of close-to-close return horizons |
| `HISTORY_LIMIT` | `500` | Maximum retained closed candles per symbol |

Periods must be positive integers; booleans and fractional periods are rejected.
EMA periods must satisfy `fast < slow < long`, volatility needs at least two
returns, and rolling-return horizons must be nonempty, unique and increasing.
History capacity must fit every configured calculation, including the extra
close needed for returns. The engine selects the Hub's first configured kline
interval by default; an explicitly selected interval must exist on the Hub.
The application currently supplies its single configured market-data interval.

### Formulas and warm-up

`C` denotes a closed-candle close. Historical calculations use only retained
closed candles. Default minimum samples below mean closed candles for historical
groups and individual current observations for the three context groups.

| Group | Values and formulas | Default minimum samples |
| --- | --- | --- |
| `trade` | Latest trade price and quantity | 1 trade |
| `returns` | Last closed `C`; simple return `(C[t]-C[t-1])/C[t-1]`; natural log return; rolling fractional returns `(C[t]-C[t-N])/C[t-N]` for N=5,10,20 | 21 |
| `trend` | EMAs 9,21,50; signed fast-minus-slow and slow-minus-long spreads; fractional `(C-EMA)/EMA` distances | 50 |
| `momentum` | Wilder RSI14; ROC10 in percent `100*(C[t]-C[t-10])/C[t-10]`; close change `C[t]-C[t-1]` | 15 |
| `volatility` | True range; ATR14; normalized ATR `ATR/C`; ATR percent `100*ATR/C`; sample standard deviation of the last 20 log returns | 21 |
| `volume` | Rolling 20-candle quote-volume sum / base-volume sum; latest base volume / mean of preceding 20 base volumes; taker-buy ratio and base-volume delta proxy | 21 |
| `microstructure` | Bid/ask and quantities; midpoint `(bid+ask)/2`; spread `ask-bid`; spread bps `10000*spread/midpoint`; top imbalance `(bid_qty-ask_qty)/(bid_qty+ask_qty)` | 1 book ticker |
| `mark_funding` | Mark/index prices; basis `mark-index`; basis percent `100*basis/index` and bps `10000*basis/index`; funding rate and signed seconds until next funding | 1 mark-price event |
| `regime` | ATR/C; `(EMA_fast-EMA_slow)/EMA_slow`; directional efficiency over 10 changes; relative volume | 21 |

EMA starts with the first N retained closes' arithmetic mean, then uses
`EMA += 2/(N+1) * (C-EMA)`. RSI seeds mean gains and losses from N changes, then
smooths each with `(previous*(N-1)+current)/N`. RSI is 100 for gain-only input,
0 for loss-only input, and 50 for flat prices.

True range is `max(high-low, abs(high-previous_close), abs(low-previous_close))`;
the first retained candle uses `high-low`. ATR seeds the mean of the first N
true ranges and applies Wilder smoothing thereafter. Realized volatility uses
sample variance with denominator `N-1`, requires N+1 closes, and is not
annualized. Directional efficiency is absolute N-change displacement divided
by the sum of absolute changes across that path. A flat path has an undefined
denominator and makes the regime group unavailable; it is not assigned a label.

VWAP uses the reported normalized quote and base volumes, not a typical-price
approximation. The taker-buy ratio is `taker_buy_volume / volume`; the explicitly
named `taker_base_volume_delta_proxy` is `2*taker_buy_volume-volume` for one
closed candle. This proxy describes that candle's supplied volumes and does not
represent exchange-wide order flow or resting book liquidity. Invalid volume
relationships, such as taker volume exceeding total volume, are rejected.
`seconds_until_funding` is signed; a negative value means the reported funding
timestamp has passed. No countdown is clamped to a synthetic zero.

### Freshness and availability

| Feature groups | Required fresh source |
| --- | --- |
| `trade` | Trade stream |
| `returns`, `trend`, `momentum`, `volatility`, `volume`, `regime` | Selected kline stream and sufficient recent, continuous closed history |
| `microstructure` | Book-ticker stream |
| `mark_funding` | Mark-price stream |

The engine reads per-stream Hub freshness, including exchange/receipt age,
connection state, generation recovery and clock skew. Unrelated stale streams
do not invalidate independent feature groups; missing depth has no effect.
Fresh updates to the current open successor candle can keep recent closed
history usable without allowing its unfinished price into indicators. That
history expires when the successor candle should have closed plus the Hub's
stale allowance (10 seconds by default), even if an obsolete open window keeps
receiving updates.

Each group reports `ready`, `warming_up`, `stale`, or `unavailable`, reasons,
and required/available sample counts. Missing required sources are unavailable;
stale required sources are stale; insufficient valid history is warming up.
Groups are atomic: if any component is undefined or invalid, the whole group's
`values` is null. Examples include a zero total book quantity, zero volume
denominators, flat directional efficiency, or arithmetic overflow. These cases
never receive invented zero values. A snapshot is `partial` when some groups
are ready and others are not; a group itself is never partial.

### History, precision and recovery

`FeatureHistory` retains at most 500 closed candles per symbol by default, plus
a bounded ordering reference. Open candles are tracked separately from closed
history. Duplicate and older observations do not add samples; future or
prematurely closed candles cannot advance the history. A revised closed candle,
overlap, observed missing close/candle gap, invalid candle, or local clock
rollback invalidates continuity-dependent history. Missing candles are never
invented. Calendar-month intervals advance by UTC month boundaries.

The engine also resets history when the selected kline connection changes
identity, status or generation, or its own subscriber queue overflows. It drains
ambiguous queued observations and can seed at most one fresh closed candle per
symbol from the Hub's current-generation cache. Another consumer's queue loss
does not reset this engine. Trade, book and mark context tolerate dropped
intermediate observations because they read the Hub's latest individual event;
closed-candle indicators must establish sufficient continuous history again.
The default longest warm-up is 50 closed candles, including after disconnects
and proactive connection rotation. There is no REST history backfill.

EMA, RSI and ATR are recomputed and reseeded from the retained bounded history.
After eviction, values can differ from calculations seeded with the full
lifetime history; this behavior is intentional and deterministic. There is no
persistent state, and application restart starts warm-up again.

Arithmetic uses a fixed 34-digit Decimal context independent of the caller's
context. Nonfinite inputs, division by zero, overflow and inexact underflow make
affected calculations unavailable. Float output is limited to log-return
statistics and time durations, with finite-value validation; price, volume and
ratio fields remain Decimal. Decimal fields serialize as JSON strings.

Depth deltas are not used for full-book imbalance or total liquidity. Those
features require a REST snapshot and update-ID reconciliation, which remain
deferred. No local order book is constructed from lossy delta queues.

### Lifecycle and read-only API

Lifespan constructs a fresh engine and Hub, registers the feature consumer
before starting an enabled feed or injected offline source, and cancels both
tasks at shutdown. Shutdown removes the subscription and clears feature
history. A disabled feed without an injected source creates no feature task;
the API reports missing/unavailable groups. Importing the application creates
no network connection or feature runtime. Source failures make affected data
stale and expose safe diagnostic codes.

`GET /features/status` returns typed per-symbol and per-group readiness plus
runtime state and history limits. `GET /features/{symbol}/latest` returns an
immutable snapshot with source timestamps, generation/freshness information,
history diagnostics, sample counts and typed feature groups. Symbols are
normalized to uppercase; unknown symbols return sanitized 404 responses.
Requests before lifespan initialization return 503. The routes expose no
mutation or execution actions and never emit NaN/Infinity.

See [the Phase 3 report](../docs/PHASE_3_REPORT.md) for validation results and
remaining operational limits. Strategy scoring, AI integration, durable history,
REST backfill, reconciled books, account access and execution adapters remain
outside Phase 3. FeatureEngine does not call the Phase 1 execution gateway.

## StrategyEngine (Phase 4)

`FeatureSnapshot -> StrategyEngine -> StrategyAssessment / StrategyCandidate`
is an analytical boundary. The three deterministic strategies consume typed
Phase 3 groups; they do not read exchange payloads, call execution adapters, or
produce `TradeIntent`/Phase 1 `SignalCandidate` records. LONG/SHORT are analytical
directions. No order quantity, leverage, order type, account data or AI is involved.

| Strategy ID | Required groups | Optional group |
| --- | --- | --- |
| `trend_following` | trend, momentum, regime, volatility | None |
| `momentum_continuation` | momentum, volume | microstructure |
| `mean_reversion` | trend, momentum, volatility, regime | microstructure |

Trend combines two normalized EMA separations, slow-EMA distance and ROC with
weights 30/30/20/20, requiring at least two components supporting the net direction.
Efficiency and normalized ATR scale conviction. Momentum combines ROC, RSI,
close-change/VWAP and taker-buy bias with weights 40/25/20/15; low relative volume
and extreme RSI reduce conviction. Reversion combines contrarian ATR-normalized
slow-EMA distance and RSI with weights 60/40, requires confirming fast-EMA distance,
and suppresses conviction during efficient trends, high volume or high ATR.

Every contribution is `weight * normalized_input * quality_multiplier`; all
component weights in one strategy sum to 100. Scores stay in `[-100,100]`.
Confidence in `[0,1]` is `abs(score)/100 * within_strategy_agreement * optional_quality`;
agreement is `abs(sum(contributions))/sum(abs(contributions))`, or zero for no
evidence. It is an engineering quality measure, not a probability of profit.

Only READY assessments enter weighted mean score. Aggregate confidence is the
weighted sum of their confidence divided by the weight of **all enabled**
strategies, multiplied by `abs(weighted_net_score)/weighted_gross_score` (zero
when gross is zero). Missing strategies reduce coverage; opposing scores offset
and reduce confidence. A ready neutral strategy still dilutes the mean score.
All individual assessments remain in the response, even when no candidate exists.

### Strategy settings and exact scoring reference

`StrategySettings` reads process environment variables with prefix `STRATEGY_`
at lifespan startup. `.env` files are not automatically loaded. Settings are
immutable and validate finite values, bounds, unique nonempty strategy selection,
and strict threshold ordering. Important defaults are:

| Suffix | Default |
| --- | --- |
| `ENABLED_STRATEGIES` | `["trend_following","momentum_continuation","mean_reversion"]` |
| `MIN_ABSOLUTE_STRATEGY_SCORE` | `25` |
| `CANDIDATE_SCORE_THRESHOLD` | `40` |
| `MIN_CANDIDATE_CONFIDENCE` | `0.55` |
| `RSI_NEUTRAL_LOW` / `RSI_NEUTRAL_HIGH` | `45` / `55` |
| `RSI_EXTREME_LOW` / `RSI_EXTREME_HIGH` | `30` / `70` |
| `MAX_ACCEPTABLE_SPREAD_BPS` | `15` |
| `TREND_EFFICIENCY_FLOOR` / `STRONG_TREND_EFFICIENCY` | `0.25` / `0.55` |
| `RELATIVE_VOLUME_BASELINE` / `RELATIVE_VOLUME_EXHAUSTION` | `1` / `3` |
| `OPTIONAL_CONTEXT_MISSING_QUALITY` | `0.75` |
| `MAX_FEATURE_AGE_SECONDS` | `10` |
| `TREND_WEIGHT` / `MOMENTUM_WEIGHT` / `MEAN_REVERSION_WEIGHT` | `1` / `1` / `1` |

See [the Phase 4 report](../docs/PHASE_4_REPORT.md) for every setting, exact
piecewise formula, evidence semantics and worked consensus examples. Thresholds
are engineering defaults; no return optimization or profitability study was done.

### Readiness, identity and lifecycle

Required groups must be ready with values, adequate closed-candle sample counts
and coherent source metadata. A missing/unavailable or warming group produces a
neutral assessment with null score/confidence and explicit reasons. Any stale
hard dependency makes that assessment stale. Unrelated stale groups do not block
independent strategies. Optional missing/stale/invalid book context retains the
score with a 0.75 confidence factor; a fresh spread scales that factor linearly
from 1 at zero bps to 0 at 15 bps. Missing optional context can therefore score
better than known poor context; it does not certify acceptable execution spread.

Both snapshot age and relevant source event/receipt ages must be strictly below
10 seconds by default; future timestamps are stale. This adds an independent
strategy limit to Phase 3 freshness. Closed history may be older than 10 seconds
while the current successor kline is fresh; the Phase 3 continuity/expiry rules
still apply. Strategies never reconstruct history or use an open candle's price.
Arithmetic overflow/inexact underflow or invalid semantic values produce no
directional assessment. Invalid typed input/settings are rejected at the boundary.

`StrategyEngine.evaluate(snapshot)` is pure and uses `snapshot.generated_at` as
its as-of time; pass `now` explicitly to evaluate age against another time.
`latest(symbol)` and `status()` read the actual FeatureEngine and use an injectable
wall clock for live freshness. No polling, subscriber, cache, history or background
task is added. Status reads evaluate each configured symbol on the application
event loop. Keep the existing single-worker operating model.

The full `snapshot_id` includes the feature read timestamp. `observation_id`
identifies enabled strategies' relevant groups, closed-candle time, history reset
and source provenance; it excludes API read time and subsequent open-kline refresh
times but retains book observation timestamps when book quality is used.
`candidate_id` hashes engine version, validated settings, observation ID and
direction. Equivalent read-time refreshes keep that ID. This supports future
deduplication but implements no persistent suppression or execution authorization.

Startup creates the StrategyEngine after the FeatureEngine and before feed tasks.
Import and OpenAPI generation construct no runtime. Shutdown continues to cancel
and await only feed/feature tasks, remove the feature subscription and clear its
history. The strategy service has nothing to cancel or persist.

`GET /strategies/status` returns version/settings identity, dependencies, weights
and per-symbol readiness. `GET /strategies/{symbol}/latest` returns source/evaluation
times, identities, assessments/evidence, consensus and an optional candidate.
Candidate thresholds are inclusive: `abs(composite_score) >= 40` and
`confidence >= 0.55`. Otherwise the aggregate direction is NEUTRAL and candidate
is null. Unknown symbols return 404; before initialization, 503. Decimal fields
serialize as strings. There is no arbitrary-feature submission endpoint.

Backtesting, durable orchestration/deduplication, strategy-to-risk integration,
account access, execution, AI and full-book reconstruction are deliberately
outside Phase 4. Existing Phase 1 risk/paper services remain separate.

## DecisionEngine (Phase 5)

`StrategySnapshot / StrategyCandidate -> DecisionEngine -> DecisionRecord`
adds deterministic analytical eligibility. The immutable record contains source
identities and timestamps, candidate direction/score/confidence/agreement,
contributors, outcome/readiness, bounded reason codes and policy/version identity.
It has no quantity, leverage, price, order type, execution mode or execution method.

| Outcome | Meaning |
| --- | --- |
| `ELIGIBLE` | A READY candidate passed validation, freshness and decision policy. This is analytical eligibility only. |
| `NO_ACTION` | A valid, fresh source has no candidate; neutral, below-threshold and warming/unavailable source results remain distinguishable by readiness. |
| `BLOCKED` | Validation/freshness failed, the symbol is unsupported, or an existing candidate failed a decision gate. Invalid/stale inputs are blocked even without a candidate. |

### Policy and validation

`DecisionSettings` reads these process environment variables at lifespan startup.
Explicit `create_app(decision_settings=...)` settings take precedence; `.env` is
not automatically loaded. There are exactly four decision settings:

| Variable | Default | Gate |
| --- | --- | --- |
| `DECISION_MAX_STRATEGY_SNAPSHOT_AGE_SECONDS` | `10` | Strategy and source feature snapshot ages must each be strictly less than this positive finite value. |
| `DECISION_MIN_DECISION_AGREEMENT` | `0.50` | Candidate requires Phase 4 agreement greater than or equal to this value in `[0,1]`. |
| `DECISION_MIN_CONTRIBUTING_STRATEGIES` | `2` | Candidate requires at least this many unique agreeing strategy families; integer in `[1,3]`. |
| `DECISION_BLOCK_INCOMPLETE_STRATEGY_COVERAGE` | `false` | When true, a candidate with incomplete strategy coverage is blocked. |

Phase 4 continues to own score/confidence thresholds (defaults 40 and 0.55).
DecisionEngine checks typed bounds and candidate threshold provenance without
recomputing scores or introducing another score/confidence cutoff. Confidence
means evidence quality; agreement means directional consensus. Neither is a
win probability. Contributor count is an engineering guard, not independent votes.

The boundary revalidates typed models, including malformed copy/construct values.
Candidate time, symbol, snapshot/observation IDs, direction and numeric values
must match the containing snapshot; its hash must match the Phase 4 formula.
Contributors must equal the supplied READY, nonzero, same-sign assessment IDs.
Incomplete coverage is preserved as a boolean and reason, even when allowed.
Reasons expose numeric observed/threshold values for age, agreement and count
failures; exception text and raw source payloads are not included.

All times must be actual timezone-aware datetimes. At decision time, feature
time must not exceed strategy time, which must not be in the future. Candidate
time must equal strategy time. Age exactly at the limit is stale. A fresh
strategy wrapper cannot conceal an old feature snapshot. DecisionEngine uses
Phase 4 readiness and does not reread feature groups or raw market events.

Malformed input produces `BLOCKED/unavailable` where safe source identifiers
can be retained; known stale/future timing produces `BLOCKED/stale` when both
source times are available. Untrusted candidate fields are omitted rather than
repaired. Missing source times remain null. Wrong input types or unsafe/missing
identifiers raise programmer errors in pure evaluation. Provider failures are
sanitized at the service/API boundary.

### Identity, API and lifecycle

`evaluate(snapshot, now=...)` requires an explicit aware evaluation time and is
pure. `latest(symbol)` uses the injected StrategyProvider and clock. A policy ID
hashes validated settings and the sorted symbol allowlist. A decision ID hashes
decision version, policy ID, symbol, upstream version/settings, observation ID,
candidate ID (or a no-candidate marker), and outcome using the existing canonical
SHA-256 helper. A later read alone does not create a new eligible identity;
changed observation, policy, upstream settings or outcome does. Evaluation/source
timestamps remain visible even when the decision ID is unchanged.

There is no cache, history, polling task, subscriber or persistent deduplication.
IDs describe analytical identity, not unique audit events or authorization.
The source IDs and scoring provenance are trusted internal producer metadata;
hash validation does not authenticate a producer or independently prove its
score calculation. The HTTP API accepts no submitted candidate/snapshot.

Lifespan constructs DecisionEngine over the existing StrategyEngine before feed
tasks start. Import/OpenAPI generation starts no runtime. Shutdown still cancels
and awaits only the existing feed/feature tasks and removes the feature subscriber.
Single-worker operation remains intended. Status evaluates symbols on demand;
it is not an atomic cross-symbol snapshot.

`GET /decisions/status` returns version, policy/ID and per-symbol outcomes/reasons.
`GET /decisions/{symbol}/latest` returns a typed DecisionRecord. Symbols are
normalized to uppercase; unknown symbols return 404. Uninitialized or unusable
providers return sanitized 503 responses; valid blocked/no-action records return
200. Mutation methods return 405. Decimal fields serialize as finite strings.

An ELIGIBLE record stops here. A future deterministic sizing layer would have to
create a concrete Phase 1 `TradeIntent`; independent `RiskEngine` evaluation
would then be required before any paper gateway use. Phase 5 does not call either
service or create either intent type. No AI, account access, private API, order
submission, backtest runner, persistence or new dependency is added.
See [the Phase 5 report](../docs/PHASE_5_REPORT.md) for exact tests and limitations.

## Offline backtesting and validation (Phase 6)

`BacktestEngine` replays finalized historical bars through the unchanged Hub,
FeatureEngine, StrategyEngine and DecisionEngine. An independent evaluator then
measures each unique eligible decision as a hypothetical signal outcome. This is
an offline Python service; no new HTTP endpoint or application lifespan work is added.

```python
import asyncio
from src.application.backtest_engine import BacktestEngine
from src.application.backtest_settings import BacktestSettings

# bars is a finite iterable of normalized KlineEvent objects, described below.
engine = BacktestEngine(
    symbols=("BTCUSDT",), interval="1m",
    settings=BacktestSettings(holding_period_bars=5),
)
report = asyncio.run(engine.run(bars))
print(report.model_dump_json(indent=2))
```

Inside an existing event loop use `await engine.run(bars)`. Optional
`feature_settings`, `strategy_settings` and `decision_settings` are fixed inputs;
they are not fitted to returns. Defaults come from their existing process
environment prefixes. Each run gets fresh replay/history/evaluation state.

### Historical input and replay

Input reuses immutable `domain.market_data.KlineEvent`: symbol, interval, aware
open/close/event/receipt timestamps, Decimal OHLC/base/quote volumes, trade count,
closed flag, taker-buy base and quote volumes. No redundant historical bar model,
file loader or network downloader is introduced.

`validate_bar` requires positive finite prices, consistent high/low/OHLC,
nonnegative volumes, taker volumes no greater than totals, and zero quote volume
when base volume is zero. Only finalized bars are accepted. Event and receipt
time must equal the exclusive interval end. Close time can equal that boundary
or end minus 1 ms; both are normalized to the exclusive UTC end. Other observed
publication latency is outside this bar-only contract. Numeric/naive timestamps
and malformed validation-bypassing model copies are refused.

Fixed intervals align to a UTC epoch grid; weekly grids anchor to Monday
1970-01-05, other fixed units to 1970-01-01. Calendar months use actual UTC month
boundaries, with multi-month alignment anchored to January 1970. Input times must
be nondecreasing. Equal-time groups are sorted by symbol; duplicates, misalignment,
older times and interval/symbol mismatches fail the run. Gaps are preserved.
`symbols` must be supplied up front; it is not inferred from future observations.

Replay advances an injected historical clock to each finalized bar's end,
publishes only that bar and calls FeatureEngine's public `latest()` to drain its
queue before evaluation. StrategyEngine and DecisionEngine receive explicit
replay time; their freshness limits are never disabled. Missing book/trade/mark
data remain missing, including the production optional-book confidence penalty.
Warm-up, bounded-history reseeding and gap invalidation remain production behavior.

An equal-time sorting iterator may read one future record to detect a group end;
it never publishes it early. Decisions at bar t cannot see t+1 prices. The replay
task only yields for startup and periodic cancellation checkpoints, never sleeps
for historical gaps. Exhaustion, input errors and cancellation clean up the
existing feature task/subscription. Direct `HistoricalReplay.frames()` consumers
must use `contextlib.aclosing` when ending iteration early; BacktestEngine does so.

### Entry, horizon and costs

| Environment variable | Default | Validation |
| --- | --- | --- |
| `BACKTEST_HOLDING_PERIOD_BARS` | `5` | Positive integer |
| `BACKTEST_FEE_BPS_PER_SIDE` | `5` | Finite, nonnegative Decimal |
| `BACKTEST_SLIPPAGE_BPS_PER_SIDE` | `2` | Finite Decimal in `[0,10000)`; effective prices must stay positive |
| `BACKTEST_CHRONOLOGICAL_SEGMENTS` | `4` | Integer in `[1,100]`; reporting only |

These are simulation assumptions, not claims about current exchange fees/fills.
`.env` files are not automatically loaded. No optimizer or best-policy selection
exists. Changing costs or segments cannot change the analytical decisions.

Decision from closed bar t enters at **open(t+1)** and exits at **close(t+H)**.
For H=1 both prices belong to the next bar. The exclusive end of t and open of
t+1 share a timestamp; event ordering is close/evaluate, then hypothetical next
open. Entry is not the source bar's close price. This assumes bar-end availability
and zero processing latency, not achievable exchange execution.

Every required intermediate bar must exist. Missing entry, missing horizon bar,
and dataset truncation produce explicit INCOMPLETE outcomes without invented
exits, returns or costs. Observed entry information can remain on incomplete
records. Unique eligible decisions overlap independently; BLOCKED/NO_ACTION
remain diagnostic. Run-local decision IDs suppress duplicates; conflicting reuse
is rejected. This is not persistent or cross-run action suppression.

For raw entry E, raw exit X, direction d=+1 LONG/-1 SHORT,
slippage s=`slippage_bps/10000`, and fee f=`fee_bps/10000`:

```text
effective_entry = E * (1 + d*s)
effective_exit  = X * (1 - d*s)
gross_return   = d * (X-E) / E
slippage_cost  = s * (1 + X/E)
fee_cost       = f * (effective_entry + effective_exit) / E
total_cost     = slippage_cost + fee_cost
net_return     = gross_return - total_cost
```

All returns normalize to the **raw entry price**, with no quantity or balance.
Both fee sides use effective prices. `returns` on a completed outcome stores
effective prices, gross return, both cost components, total cost and net return.
MFE is nonnegative and MAE nonpositive, measured from raw entry using highs/lows
of t+1 through t+H only. They exclude the source bar, post-exit bars and costs.
Arithmetic uses a fixed 34-digit Decimal context; invalid/nonfinite arithmetic
fails rather than yielding a synthetic result.

### Metrics, cohorts and segments

The immutable report retains sampled DecisionRecords with optional numeric regime
inputs, completed/incomplete outcomes, IDs, counts and summaries. Input count is
in metadata. LONG/SHORT counts cover eligible outcomes including incomplete ones.
Win/loss/flat, returns and costs use only completed signals, in deterministic
`(exit_time, decision_time, symbol, decision_id)` order.

- Win rate is `wins/(wins+losses)`, excluding flats; undefined is null.
- Expectancy is mean net return per completed signal, including flats. Mean gross,
  median net, return/cost sums and best/worst net results are also reported.
- `gross_profit` sums positive **net** signal returns; `gross_loss` is the absolute
  sum of negative **net** returns. These differ from pre-cost `sum_gross_returns`.
  Profit factor is profit/loss. Zero loss yields null with `no_losses`,
  `no_nonflat_outcomes`, or `no_completed_outcomes`; loss-only yields zero.
- Flats break both consecutive win/loss streaks.
- The normalized additive curve starts at 1 and adds each net signal return.
  Drawdown is `(running_peak-current_value)/running_peak`; maximum is reported.
  The curve can be negative and drawdown exceed 1. It is not compounded capital,
  margin, liquidation or account drawdown.

Cohorts cover symbol, direction (including NEUTRAL diagnostics), decision outcome
and source incomplete-coverage flag. `not_marked_incomplete` does not claim all
strategies were ready. Numeric regime inputs stay on sampled decisions; no opaque
category or clustering is invented.

N chronological segments divide the entire historical open-to-final-close range
into equal elapsed-time spans. Decisions belong to `[start,end)`, with the final
end included. Only horizons fully ending by that segment's end can score there;
cross-boundary horizons count as incomplete/boundary-censored even if the full
run later completes them. No future return contributes to an earlier segment.
Thus segment completed/return totals need not sum to full-run totals. Settings
remain unchanged throughout; this is walk-forward reporting, not optimization.

### Identities and resource limits

Dataset identity incrementally hashes canonical normalized records in replay
order. Decision identity remains Phase 5's. Outcome identity includes decision,
backtest settings, source bar, observed horizon evidence and completion/reason.
Run identity combines dataset, all supplied settings identities, symbol/interval
scope and analytical/backtest versions. There are no random or wall-clock run IDs.
Retain supplied configurations with the report; metadata stores their hashes.

Input is single-pass with O(symbols) ordering look-ahead. Feature history remains
bounded (500 per symbol by default). Pending horizon state is O(symbols*H) under
one-decision-per-bar sampling; each pending item hashes evidence incrementally.
Decision dedupe, final decisions/outcomes and report curves use O(input decisions)
memory for a finite run. No complete feature/strategy snapshot history or duplicate
raw-bar dataset is retained. Work includes existing bounded feature calculations
per bar, O(H) active horizon work, and sorting/grouping for final metrics.

No API/account access, credentials, intent creation, risk approval, gateway call,
real quantity, leverage, AI, P2P, database, optimization or full order book is
introduced. Signal-level validation omits funding, market impact, queue priority,
account constraints and exchange latency. Historical results cannot establish
future profitability. See [the Phase 6 report](../docs/PHASE_6_REPORT.md).

## Offline shared-capital paper portfolio (Phase 7)

Phase 6 scores independent signals; `PaperPortfolioEngine` adds shared **virtual
capital units**, with deterministic reservations and exposure/drawdown gates.
It reuses the same finalized KlineEvent contract and HistoricalReplay. There is
no new HTTP route, application background task, dependency or exchange connection.

```python
from src.application.paper_portfolio_engine import PaperPortfolioEngine
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.application.backtest_settings import BacktestSettings

engine = PaperPortfolioEngine(
    symbols=("BTCUSDT", "ETHUSDT"), interval="1m",
    settings=PaperPortfolioSettings(),
    backtest_settings=BacktestSettings(holding_period_bars=5),
)
report = await engine.run(bars)  # finite typed iterator; asyncio.run outside a loop
print(report.model_dump_json(indent=2))
```

Optional feature/strategy/decision settings remain fixed validation inputs.
Portfolio settings read `PORTFOLIO_` process variables without loading `.env`:

| Suffix | Default | Bounds |
| --- | --- | --- |
| `INITIAL_VIRTUAL_EQUITY` | `100000` | Positive finite Decimal |
| `TARGET_POSITION_FRACTION` | `0.10` | `(0,1]` |
| `MAX_GROSS_EXPOSURE_FRACTION` | `0.40` | `(0,1]` |
| `MAX_SYMBOL_EXPOSURE_FRACTION` | `0.15` | `(0,max gross]` |
| `MAX_OPEN_POSITIONS` | `4` | Strict positive integer |
| `MAX_DRAWDOWN_FRACTION` | `0.20` | `(0,1)` |
| `ONE_POSITION_PER_SYMBOL` | `true` | Explicit true/false parsing; false is rejected as unsupported |

No pyramiding, reversal or partial allocation is implemented. Desired notional
is `current_marked_equity * target_position_fraction`; confidence is not a size
multiplier or probability. Reservations immediately count toward both exposure
and position-count capacity. LONG and SHORT notionals add; they do not net.

At each complete market timestamp, apply previously reserved entries from the
current bars' opens, process all close marks/exits, then rank current decisions
by descending absolute score, confidence, agreement, followed by ascending symbol
and decision ID. All-or-none gates run against state including earlier reservations
in this rank order. The ledger sees only that group's immutable observations;
the grouping iterator's next-time frame cannot affect its sizing or arbitration.

Only ELIGIBLE upstream records can reserve. BLOCKED/NO_ACTION are ignored
diagnostically. Invalid/stale/unknown state, nonpositive equity, drawdown at or
above the limit, active symbol, maximum open-plus-reserved count, gross capacity
and symbol capacity reject with stable reason codes. State and decision times
must exactly match the explicit historical evaluation boundary. The upstream
decision is unchanged. Equivalent duplicate reads are suppressed; conflicting
identity reuse fails. Dedupe is run-local, not durable action suppression.

Entry remains `open(t+1)` and exit `close(t+H)`, with H=5, fee=5 bps and slippage=2
bps per side by default from BacktestSettings. Source close and next open share
an exclusive boundary timestamp but may have different prices. Entries are
represented when finalized next-bar data arrive, with no same-source-close fill.
Reservations fix notional before future prices are visible. The unused Phase 6
segment setting remains in the reused settings identity; it does not segment
the Phase 7 curve.

For notional N, raw entry E, known close C, direction d=+1 LONG/-1 SHORT,
s=slippage_bps/10000 and f=fee_bps/10000, open marks are:

```text
gross_mark = N * d * (C-E)/E
entry_slippage = N*s
entry_fee = N*f*(1+d*s)
unrealized_net = gross_mark - entry_slippage - entry_fee
realized_equity = initial_equity + sum(completed_net_pnl)
marked_equity = realized_equity + sum(known_unrealized_net)
peak = max(initial_equity, all prior/current known marked equities)
drawdown = (peak-marked_equity)/peak
gross_exposure = open_fixed_notional + reserved_fixed_notional
gross_exposure_fraction = gross_exposure/marked_equity, if equity > 0
```

On close, each PnL/cost component is N times the corresponding Phase 6
`outcome_returns` component, including two-sided costs. The old unrealized mark
is removed; full net PnL is realized once. `total_closed_pnl` excludes entry costs
on unfinished positions, which appear separately as outstanding entry fee and
slippage costs. Arithmetic uses the existing 34-digit Decimal context. PnL
reconciliation tolerates only `1e-32 * largest component` for separately rounded
multiplications; net remains exactly the calculated `N * net_return`.

Limits constrain new reservations. Existing exposure fractions can rise after
costs/losses, even above one if equity collapses; the model does not borrow or
fabricate liquidation. Nonpositive equity is preserved and blocks new capacity.
Drawdown recovery permits later reservations if the other gates pass.

A missing exact entry bar expires its reservation and releases capacity. A
missing holding bar makes exposure INCOMPLETE; total marked equity/drawdown/
exposure fraction become null, and new reservations remain blocked. Later prices
cannot repair that unknown path. Other existing positions can finish. Dataset-end
reservations expire; still-open positions remain incomplete, with no fabricated
exit or final mark. Previously known curve points remain unchanged. Report status
is INCOMPLETE for any reservation expiry or incomplete position.

Metrics cover input/upstream/portfolio counts, opened/completed/incomplete and
LONG/SHORT counts, initial/final equity, closed gross/fee/slippage/net totals,
outstanding entry costs, realized return, peak and maximum known drawdown,
maximum gross notional/observed positive-equity fraction, peak simultaneous open
count (including H=1 positions), average close-snapshot open count, turnover,
win/loss/flat, win rate, symbol PnL/counts and rejection reasons. Turnover is
`sum(opened virtual notionals)/initial equity`; win rate excludes flats and is
null if undefined. `valuation_complete` and `nonpositive_equity_observed` qualify
the result. Maxima are sampled observations, not intrabar risk guarantees.

Canonical IDs cover policy settings, decision/state/action, reservation inputs,
entry/horizon evidence and full run settings/dataset/version scope. The report
uses `metadata.run_id`; there is no random ID or wall-clock run time. Retain the
supplied settings and code revision alongside it.

Each run uses fresh state and cleans up the existing replay consumer on completion,
error or cancellation. Input grouping is O(symbols); active positions/reservations
are bounded by configured capacity, and feature history remains bounded. Finite
audit records and curve snapshots grow with decisions/timestamps (each state
includes symbol exposures); no whole raw/feature dataset is retained.

Phase 1 RiskEngine/PaperExecutionGateway are intentionally not called: their
quantity-bearing execution contracts and process-local fill/approval history do
not define this deterministic virtual ledger. No intent, real quantity, account
access, private endpoint, credential, order, AI/ML, optimizer or database is added.
Funding, market impact, intrabar paths, margin/liquidation, persistence and actual
execution orchestration remain deferred. This is no profitability guarantee.
See [the Phase 7 report](../docs/PHASE_7_REPORT.md) for exact validation evidence.
