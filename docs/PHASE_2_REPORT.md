# Phase 2 completion report

Validated on 2026-09-08, branch `phase-2-market-data`. No commits or pushes were
performed. Existing uncommitted Phase 1 work was retained throughout.

## Files created in Phase 2

- `backend/src/domain/market_data.py`
- `backend/src/application/market_data_hub.py`
- `backend/src/infrastructure/binance/__init__.py`
- `backend/src/infrastructure/binance/stream_router.py`
- `backend/src/infrastructure/binance/settings.py`
- `backend/src/infrastructure/binance/parsers.py`
- `backend/src/infrastructure/binance/public_market_data.py`
- `backend/src/api/__init__.py`
- `backend/src/api/market_data.py`
- `backend/tests/conftest.py`
- `backend/tests/test_market_data_models.py`
- `backend/tests/test_binance_router.py`
- `backend/tests/test_binance_parsers.py`
- `backend/tests/test_binance_transport.py`
- `backend/tests/test_market_data_hub.py`
- `backend/tests/test_market_api.py`
- `docs/PHASE_2_REPORT.md`

## Files modified in Phase 2

- `.env.example`: public feed configuration, still paper by default.
- `backend/requirements.txt`: direct `websockets>=17.1,<18` dependency; the tested
  environment already had 17.1 through Uvicorn's dependencies.
- `backend/src/main.py`: app factory, feed task lifespan, sanitized failure state,
  read-only market router. Existing health/config responses remain intact.
- `README.md`, `backend/README.md`, `docs/ARCHITECTURE.md`: Phase 2 interfaces,
  configuration, official sources, and limitations.

The modified Phase 1 risk/model/executor files and their tests, plus untracked
`test_api.py` and `test_models.py`, predated Phase 2. They were preserved and are
included in the final full-suite result; they are not new Phase 2 changes.

## Binance stream mapping

| Stream per lowercase symbol | Route | Selected update frequency |
| --- | --- | --- |
| `@aggTrade` | `/market` | 100 ms aggregation |
| `@kline_1m` | `/market` | 250 ms when updates exist |
| `@markPrice@1s` | `/market` | 1 second |
| `@bookTicker` | `/public` | Best bid/ask changes |
| `@depth` | `/public` | Default 250 ms; no `@250ms` suffix |

Eight default symbols: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT,
DOGEUSDT, LINKUSDT. Two combined URLs use
`wss://fstream.binance.com/{route}/stream?streams={stream1}/{stream2}/...`:
24 market streams and 16 public streams.

Contracts were verified against official Binance documentation on 2026-09-06:

- [Routing notice](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice)
- [Connection behavior](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect)
- [Market payload catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market)
- [Public payload catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public)

## Architecture and recovery

Domain events use immutable Pydantic models, Decimal numeric values, exchange
event timestamps, and local receive timestamps. The Binance adapter normalizes
and validates JSON before delivering it through exchange-independent source/sink
protocols. Combined envelopes must match the subscribed stream, symbol, and type.
Malformed messages are counted and discarded with safe errors. Additive exchange
fields are tolerated; a supplied non-USD-M symbol type is rejected.

Each route runs independently in one asyncio task. Opening, receiving, and closing
are bounded, as are message size and frame buffers. Built-in `websockets` protocol
behavior answers Binance server pings with matching pong payloads; no custom
heartbeat implementation was added. Client-initiated pings are disabled.

Failures use exponential backoff with equal jitter, bounded by the configured
minimum and maximum (defaults 1 and 30 seconds). A handshake or brief valid burst
does not reset backoff. A session must deliver fresh data and last at least the
receive timeout before the next retry resets. Reopening the same combined URL
restores all subscriptions. A route-wide fresh-data deadline also prevents
malformed or obsolete traffic from keeping a useless connection alive.

Connections rotate at 86,100 seconds, five minutes before the 24-hour limit.
Every successful connection increments a route generation, including after
cancellation/restart of the same source. Old caches remain stale until that
generation receives newer observations. Cancellation during connection opening,
reading, or backoff stops tasks and closes established sockets.

MarketDataHub maintains bounded latest state per symbol/type/interval and bounded
subscriber queues. Slow consumers drop their oldest queued observation, with
overflow counted. A symbol is stale if any expected stream is missing, disconnected,
awaiting recovery, affected by clock skew, or past the age threshold. Both exchange
and receipt times matter; mark-price next-funding time is never used for freshness.
Replays and out-of-order observations do not refresh timestamps. A separate bounded
coherent ordering reference allows recovery from future-dated observations.

Depth remains normalized delta events with update IDs and zero-quantity deletions;
no levels are combined into a local book. Sequence resets after a new connection
require an advancing exchange timestamp and imply no continuity guarantee.

The read-only API provides `GET /market/status` and `GET /market/{symbol}/latest`,
including freshness and connection state. Decimal values serialize as strings.
Application import has no network side effects. Lifespan owns startup/shutdown.
Unexpected source failures become a safe `source_failed` status.

## Commands and exact results

Commands ran from `backend` with `.venv/Scripts/python.exe` (Python 3.11.9).
The initial backend baseline was **229 passed**. A resumed baseline was
**229 passed, 2 warnings in 0.82s**.

Meaningful batch checks completed during implementation:

- Models: **86 passed in 0.18s**.
- Models + initial router/settings: **121 passed in 0.27s**.
- Parsers: **185 passed in 0.30s**.
- Initial hub + models: **140 passed in 0.30s**.
- API + existing Phase 1 API: **28 passed, 2 warnings in 0.73s**.
- Hub recovery regressions: **73 passed in 0.25s**.
- All Phase 2 tests before final source-restart fix: **444 passed, 2 warnings in 1.30s**.
- Transport + hub + API after source-restart fix: **138 passed, 2 warnings in 0.86s**.

Final targeted command:

```text
python -m pytest tests/test_market_data_models.py tests/test_binance_router.py tests/test_binance_parsers.py tests/test_binance_transport.py tests/test_market_data_hub.py tests/test_market_api.py -q
446 passed, 2 warnings in 1.13s
```

Final complete backend command:

```text
python -m pytest
675 passed, 2 warnings in 1.45s
```

Final Phase 2 counts: models 86, router/settings 37, parsers 185, transport 49,
hub 73, market API 16. All 229 existing Phase 1 tests also pass.

Additional validation:

- App import and four expected OpenAPI paths: **OK**. An initial check incorrectly
  assumed every `app.routes` entry had `.path`; it was corrected to inspect OpenAPI.
  No application change was needed for that check.
- `python -m pip check`: **No broken requirements found.**
- `python -m uvicorn src.main:app --host 127.0.0.1 --port 8765`, with
  `BINANCE_MARKET_DATA_ENABLED=false`: application startup completed. Local GETs
  to `/health`, `/system/config`, `/market/status`, `/market/BTCUSDT/latest` all
  returned **HTTP 200**. Config reported `paper`; market status reported both
  connections disabled and data stale. Ctrl+C completed application shutdown.
- `git diff --check`: no whitespace errors. Git emits Windows LF/CRLF conversion
  notices for the working copy.

Sandbox directory-access failures required running tests with authorized
escalation. Tests use mocked transport and injected sources, never live Binance.

## Warnings and remaining limits

Two dependency warnings remain, also present in the resumed baseline:

1. Starlette deprecates TestClient's `httpx` integration in favor of `httpx2`.
2. Starlette uses deprecated `anyio.abc.BlockingPortal`.

No required Phase 2 implementation is unfinished. Live Binance connectivity,
24-hour soak testing, and sustained throughput under production load were not
tested. Connectivity can depend on geographic/network access. Clock skew and
quiet streams can conservatively mark data stale.

State is process-local and lost on restart. Use a single application worker;
multiple workers create independent sockets/caches. Reconnect gaps are not
backfilled. Subscribers are lossy and cannot serve as durable audit logs or
reconstruct a book. Public book feeds omit RPI orders. Phase 2 freshness is exposed
for later consumers, not wired into Phase 1 execution. Strategies/FeatureEngine
remain Phase 3. REST snapshot reconciliation, history/persistence, account access,
and order execution are outside this phase. No private streams or credentials
were introduced.
