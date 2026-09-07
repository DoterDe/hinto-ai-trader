# Backend

Phase 1 and Phase 2 backend for Hinto AI Trader.

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
observations. After a new connection, sequence IDs may restart only when the
exchange timestamp advances; this does not establish depth continuity.

Consumers use `MarketDataHub.subscribe()` as a context manager and await its bounded
queue of normalized events. Slow consumers lose their oldest queued observations;
the aggregate drop count is visible in status. Consumers needing continuity must
detect gaps using their own requirements. Latest-state memory is bounded by
configured symbols/streams; no historical time series is stored.

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

## Next phase

Feature extraction and strategy scoring remain Phase 3. Durable history, REST
backfill, reconciled order books, account integration, and execution adapters
are outside this Phase 2 implementation.
