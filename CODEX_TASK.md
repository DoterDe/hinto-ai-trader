# Current Codex Task — Phase 3: FeatureEngine

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, and `docs/PHASE_2_REPORT.md` completely before editing.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small reviewable batches, run targeted tests after each batch, then run the complete backend suite. Do not perform a broad repository rewrite.

The working branch is `phase-3-feature-engine`. Phase 2 has already been merged into `main` and the accepted baseline is **675 backend tests passing**.

## Objective
Build an exchange-independent **FeatureEngine** that consumes normalized market observations from Phase 2 and produces deterministic, typed feature snapshots for future strategy modules.

Architecture:

```text
MarketDataHub
    -> FeatureEngine
    -> FeatureSnapshot
    -> future StrategyEngine
```

FeatureEngine must not generate trading decisions, TradeIntent, AI decisions, or execution requests.

## Non-negotiable boundaries
Do not add:
- BUY/SELL/LONG/SHORT decisions,
- strategy scoring,
- SignalCandidate generation,
- AI Advisor or OpenAI API,
- DecisionEngine changes,
- private Binance streams,
- account balances or positions,
- Binance API keys,
- order submission,
- testnet or live execution,
- database/Redis,
- frontend redesign,
- ML/RL models,
- hyperparameter optimization,
- full local order book reconstruction.

FeatureEngine must never directly reach an ExecutionGateway.

## Baseline first
Before editing:
1. confirm `git branch --show-current` is `phase-3-feature-engine`;
2. confirm `git status`;
3. run the complete existing backend suite;
4. inspect at minimum:
   - `backend/src/domain/market_data.py`
   - `backend/src/application/market_data_hub.py`
   - Phase 2 market-data tests
   - `docs/ARCHITECTURE.md`
   - `docs/PHASE_2_REPORT.md`.

Do not redesign Phase 1 or Phase 2 unless required for compatibility.

## Core principles
1. Deterministic calculations.
2. Typed immutable outputs.
3. Exchange-independent domain/application code.
4. Explicit warm-up/readiness state.
5. Never treat stale or missing required market data as valid.
6. Avoid look-ahead bias.
7. Closed-candle indicators use closed candles unless explicitly documented otherwise.
8. Preserve `Decimal` where precision matters; use float only for numerical calculations where justified.
9. Keep bounded process-local history.
10. Prefer small explicit rolling calculations; do not add pandas unless clearly necessary.
11. Tests must be deterministic and offline.
12. Never silently replace unavailable/invalid features with arbitrary zeroes.

## Required FeatureSnapshot
Create a typed per-symbol feature snapshot containing at minimum:
- symbol,
- generated_at,
- relevant source timestamps,
- readiness state,
- stale/unavailable reasons,
- feature-group availability,
- typed feature values.

Feature values must remain unavailable/null during warm-up or when required data is stale/missing.

## Required feature groups

### 1. Price / returns
Implement:
- latest trade/mark context,
- candle close,
- simple return,
- log return where valid,
- rolling return over configurable windows.

Candle-derived historical calculations must use closed candles.

### 2. Trend
Implement:
- EMA fast,
- EMA slow,
- EMA long,
- EMA spreads,
- price distance from EMA,
- multi-window numerical trend context.

Default periods:
- EMA fast: 9
- EMA slow: 21
- EMA long: 50

Do not convert these into trading labels or decisions.

### 3. Momentum
Implement:
- RSI,
- ROC / rate of change,
- close-to-close candle momentum.

Default RSI period: 14.
Handle all-gain, all-loss, and flat-price cases explicitly and test them.

### 4. Volatility
Implement:
- true range,
- ATR,
- normalized ATR / ATR percentage,
- rolling realized volatility.

Default ATR period: 14.
No future candles may be used.

### 5. VWAP / volume
Implement:
- bounded rolling VWAP suitable for the Phase 2 data model,
- relative volume,
- taker-buy volume ratio,
- a clearly named volume-delta proxy derived only from available normalized data.

Document exactly what the volume-delta proxy means and what it does not mean. Do not claim exchange-wide true order-flow delta unless the available data proves it.

### 6. Spread / microstructure
Using BookTicker implement:
- bid,
- ask,
- midpoint,
- absolute spread,
- spread in basis points,
- top-of-book bid quantity,
- top-of-book ask quantity,
- top-of-book imbalance.

Suggested imbalance formula:

```text
(bid_qty - ask_qty) / (bid_qty + ask_qty)
```

Handle zero denominator safely.

### 7. Depth context
Phase 2 depth is **deltas only**, not a reconstructed book.

Therefore:
- do not compute full-book depth imbalance from raw depth deltas;
- do not call delta quantities total bid/ask liquidity;
- only expose clearly named delta/update statistics if useful;
- defer full-book features until REST snapshot + update-ID reconciliation exists.

### 8. Mark/funding context
Using MarkPriceEvent implement:
- mark price,
- index price,
- mark/index basis,
- basis percentage/bps,
- funding rate,
- time until next funding where useful.

These are contextual features only.

### 9. Market-regime inputs
Expose deterministic numerical inputs such as:
- normalized volatility,
- EMA separation,
- directional efficiency / deterministic trend-strength input,
- relative volume.

Prefer raw numerical inputs. If a descriptive enum is added, it must be deterministic, documented, threshold-tested, and never drive execution directly.

## History/state design
Implement an application-level bounded rolling history mechanism that:
- is per symbol,
- has an explicit maximum size,
- accepts normalized events only,
- does not depend on Binance classes,
- handles duplicates and out-of-order events conservatively,
- distinguishes open and closed klines,
- does not invent missing historical candles,
- keeps closed-candle history suitable for indicator windows,
- invalidates or marks continuity-dependent state conservatively when needed.

Do not add persistent storage in Phase 3.

## Freshness integration
This is critical.

FeatureEngine must consume freshness information from `MarketDataHub` and must not mark a feature group ready/fresh when its required source is stale or missing.

Examples:
- spread/microstructure -> requires fresh BookTicker;
- funding/basis -> requires fresh MarkPrice;
- candle indicators -> require enough fresh closed Kline history;
- trade-derived features -> require fresh trades.

An unrelated stale stream should not automatically invalidate an independent feature group unless that group depends on it.

Partial availability must be explicit in FeatureSnapshot.

## Lossy subscriber handling
`MarketDataHub.subscribe()` uses bounded lossy queues.

Do not silently claim continuity-dependent features remain valid after an observed gap. Document which features tolerate loss and apply conservative invalidation/readiness where needed. Do not build a local order book from lossy deltas.

## Suggested structure
Prefer something close to:

```text
backend/src/
  domain/
    features.py
  application/
    feature_engine.py
    feature_history.py
  indicators/
    __init__.py
    trend.py
    momentum.py
    volatility.py
    volume.py
    microstructure.py
  api/
    features.py
```

Adjust only after inspecting the repository and explain deviations.

Keep indicator functions pure where practical.

## Configuration
Add typed configuration with conservative defaults:

```text
EMA_FAST=9
EMA_SLOW=21
EMA_LONG=50
RSI_PERIOD=14
ATR_PERIOD=14
ROC_PERIOD=10
VOLATILITY_WINDOW=20
RELATIVE_VOLUME_WINDOW=20
VWAP_WINDOW=20
HISTORY_LIMIT=500
```

Validate positive integers, sensible period ordering, and sufficient history capacity.

Do not add excessive optimization parameters.

## Feature API
Add read-only endpoints such as:
- `GET /features/status`
- `GET /features/{symbol}/latest`

Responses must clearly distinguish ready, warming-up, stale, and unavailable feature groups.

Unknown symbols should return 404. Do not emit NaN/Infinity in JSON. No mutation/execution endpoints.

## FeatureEngine lifecycle
Prefer integrating through the existing `MarketDataHub` subscription mechanism rather than coupling to Binance.

The engine should:
1. consume normalized events,
2. maintain bounded rolling state,
3. update deterministic feature snapshots,
4. expose latest state to read-only API consumers.

Integrate cleanly with the existing FastAPI lifespan without introducing network side effects at import time.

## Numerical safety
Explicitly guard:
- zero denominators,
- empty windows,
- one-element variance windows,
- invalid log-return inputs,
- Decimal-to-float conversion,
- NaN,
- Infinity,
- timestamp ordering.

Do not hide invalid states by substituting fake zeros.

## Testing requirements
Add comprehensive deterministic offline tests. At minimum cover:
- EMA known sequence,
- RSI known sequence,
- RSI all gains,
- RSI all losses,
- RSI flat prices,
- ATR known OHLC sequence,
- ROC,
- simple/log/rolling returns,
- realized volatility,
- VWAP,
- relative volume,
- taker-buy ratio,
- midpoint,
- spread,
- spread bps,
- top-of-book imbalance,
- mark/index basis,
- funding context,
- warm-up behavior,
- insufficient history,
- stale required stream,
- missing required stream,
- fresh recovery,
- duplicate events,
- out-of-order candles,
- open vs closed candle behavior,
- bounded history,
- no NaN/Infinity outputs,
- unknown symbol API behavior,
- API responses,
- Phase 1 + Phase 2 regressions.

Use fixed fixtures and independent expected values; do not test formulas by reusing the production implementation to calculate the expected result.

## Documentation
Update:
- `CODEX_TASK.md`,
- `docs/ARCHITECTURE.md`,
- `backend/README.md`,
- root README only if needed.

Create `docs/PHASE_3_REPORT.md` at completion.

Document:
- formulas,
- default windows,
- warm-up requirements,
- freshness dependency matrix,
- precision choices,
- closed-candle rules,
- history behavior,
- known limitations,
- why depth-book imbalance is deferred,
- why outputs are features, not trading signals.

## Development batches
### Batch 1
- domain feature models,
- typed settings,
- pure indicator primitives,
- formula tests.

### Batch 2
- bounded feature history,
- closed-candle handling,
- duplicate/out-of-order handling,
- tests.

### Batch 3
- FeatureEngine integration with MarketDataHub,
- freshness/readiness/partial availability,
- tests.

### Batch 4
- read-only Feature API,
- app lifecycle integration,
- tests.

### Batch 5
- documentation,
- regression review,
- full suite.

After each meaningful batch run targeted tests and fix failures before continuing.

## Completion commands
At minimum run:

```bash
cd backend
python -m pytest
python -m pip check
```

Also run:
- application import/OpenAPI check,
- appropriate offline startup/shutdown smoke test,
- `git diff --check`,
- `git status`,
- `git diff --stat`.

Do not commit or push automatically.

## Acceptance criteria
Phase 3 is complete only when:
1. FeatureEngine consumes exchange-independent normalized events.
2. FeatureSnapshot is typed and deterministic.
3. Required features are implemented and independently tested.
4. Closed-candle calculations avoid look-ahead behavior.
5. Warm-up state is explicit.
6. Required stale/missing sources make affected feature groups unavailable.
7. Partial feature availability is represented correctly.
8. History is bounded.
9. No full order book is falsely reconstructed.
10. No strategy/trading decision is generated.
11. No AI provider is added.
12. No execution/private/account capability is added.
13. All existing 675 baseline tests still pass.
14. New Phase 3 tests pass.
15. Documentation is updated.

## Completion report
At the end report:
- baseline test result,
- files created,
- files modified,
- formulas used,
- window defaults,
- warm-up rules,
- freshness dependency matrix,
- history design,
- FeatureEngine lifecycle,
- API endpoints,
- exact targeted test results,
- exact complete test result,
- warnings,
- intentionally deferred work,
- remaining technical risks.

Do not commit or push until reviewed.
