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

## Planned phases

1. Domain + RiskEngine + PaperExecution + FastAPI scaffold.
2. Binance public market data for 8 symbols.
3. FeatureEngine and multi-strategy scoring.
4. AIAdvisor interface + structured-output provider.
5. Backtesting and persistence.
6. React dashboard.
7. Binance testnet adapter and order reconciliation.
8. Reliability tests: disconnects, stale streams, duplicate events, malformed AI output.
