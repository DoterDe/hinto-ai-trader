# Current Codex Task — Phase 2: Binance Public Market Data

Read `AGENTS.md` and `docs/ARCHITECTURE.md` first.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small batches, and verify each batch with tests. Do not perform a broad repository rewrite.

## Objective
Implement a resilient **public market-data layer for Binance USDⓈ-M Futures** for eight symbols. This phase must not use private account credentials and must not implement real-money execution.

## Symbols
- BTCUSDT
- ETHUSDT
- SOLUSDT
- BNBUSDT
- XRPUSDT
- ADAUSDT
- DOGEUSDT
- LINKUSDT

## Important current Binance WebSocket routing
Binance USDⓈ-M Futures now routes WebSocket market streams by data type. Do not assume the older unrouted base URL works for every stream.

Base: `wss://fstream.binance.com`

Current routed endpoints:
- high-frequency public market data: `/public`
- regular market data: `/market`
- private user data: `/private` — NOT USED IN THIS PHASE

Examples from current Binance documentation:
- `wss://fstream.binance.com/market/ws/bnbusdt@aggTrade`
- `wss://fstream.binance.com/public/ws/bnbusdt@depth/ethusdt@depth`
- `wss://fstream.binance.com/market/stream?streams=bnbusdt@aggTrade/btcusdt@markPrice`

Before finalizing stream mappings, verify each selected stream against the current official Binance USDⓈ-M Futures documentation. Do not guess endpoint routing.

## Required architecture
Create exchange-specific infrastructure behind a domain/application-facing interface.

Suggested structure:

```text
backend/src/
  domain/
    market_data.py
  application/
    market_data_hub.py
  infrastructure/
    binance/
      __init__.py
      stream_router.py
      public_market_data.py
      parsers.py
  api/
    market_data.py
```

Adjust names only if the existing repository structure makes another layout clearly cleaner. Do not move unrelated Phase 1 files.

## Required domain models
Use typed models for normalized events. At minimum:
- `TradeEvent`
- `KlineEvent`
- `BookTickerEvent`
- `MarkPriceEvent`
- `DepthEvent` or a clearly documented depth-update model
- `MarketConnectionState`

Normalized events must include where applicable:
- symbol
- exchange event timestamp
- local receive timestamp
- event type
- relevant numeric values using appropriate numeric types

Keep raw Binance payloads out of strategy/domain code.

## MarketDataHub responsibilities
Implement a service that:
1. receives normalized Binance events,
2. stores the latest snapshot/state needed by downstream services,
3. exposes per-symbol freshness/last-update information,
4. allows consumers to subscribe without importing Binance-specific code,
5. does not contain strategy logic.

## WebSocket client requirements
Implement:
- async connection lifecycle,
- combined streams where appropriate,
- explicit routing between `/public` and `/market`,
- lowercase symbols in stream names,
- reconnect with bounded exponential backoff + jitter,
- resubscribe/state recovery after reconnect,
- connection-state reporting,
- stale-data detection,
- clean cancellation/shutdown,
- malformed-message handling without crashing the whole service,
- ping/pong compatibility with Binance WebSocket behavior,
- proactive handling of Binance's 24-hour connection lifetime.

Do not create one WebSocket per symbol unless there is a demonstrated need. Prefer a small number of routed combined connections.

## Initial streams
Implement and test these market-data capabilities, choosing the correct current Binance route for each:
- aggregate trades,
- klines/candles,
- book ticker,
- mark price,
- depth/order-book updates.

For klines, start with one configurable interval (default `1m`) but design the stream builder so more intervals can be added later.

## Order-book scope
Do NOT build a production local order book from depth deltas unless the required REST snapshot + update-ID reconciliation algorithm is implemented correctly.

For this phase either:
A. expose depth updates as normalized events only, or
B. implement the official Binance snapshot + buffered-delta reconciliation algorithm with dedicated tests.

Prefer A for Phase 2 unless there is a strong architectural reason for B.

## API requirements
Extend FastAPI with read-only endpoints such as:
- `GET /market/status`
- `GET /market/{symbol}/latest`

Responses must show data freshness and connection state. Do not expose credentials or internal exception traces.

Optionally add a backend WebSocket endpoint for normalized live market events if it stays small and testable.

## Configuration
Add settings for:
- symbol list,
- kline interval,
- stale threshold,
- reconnect min/max delay,
- Binance WebSocket base URL only if useful for tests.

Defaults must work for public market data without API keys.

## Testing
Add deterministic tests that do not depend on Binance being online:
- stream-name/router generation,
- parsing representative payload fixtures,
- malformed payload behavior,
- reconnect/backoff policy,
- freshness/stale-state calculation,
- MarketDataHub latest-state updates.

Network integration tests, if added, must be clearly separated/optional.

## Dependencies
Add the minimum dependency needed for async WebSocket support. Avoid unnecessary SDKs if a small direct WebSocket client is sufficient.

## Do not do in Phase 2
- no API keys,
- no Binance account/user-data stream,
- no order submission,
- no live-money execution,
- no AI provider,
- no strategy logic,
- no frontend redesign,
- no large copy/paste of Hinto modules.

## Commands to run
At minimum:

```bash
cd backend
python -m pytest
```

Also run the application import/startup check appropriate for the implemented code.

## Acceptance criteria
Phase 2 is complete only when:
1. all eight configured symbols are supported by the stream builder,
2. `/public` vs `/market` routing is explicit and tested,
3. raw payloads are normalized before reaching application/domain consumers,
4. stale state can be detected per symbol,
5. reconnect logic is testable,
6. existing Phase 1 tests still pass,
7. new tests pass,
8. no secrets or private Binance endpoints were introduced,
9. documentation is updated if architecture changed.

## Completion report
Return:
- files changed,
- tests/commands executed and exact results,
- current stream-to-route mapping used,
- architecture decisions,
- anything intentionally deferred to Phase 3,
- remaining technical risks.
