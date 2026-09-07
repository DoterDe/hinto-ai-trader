# Hinto AI Trader

AI-assisted crypto market research and paper-trading workstation inspired by the open-source Hinto Trader project.

> **Safety scope:** this repository is intentionally paper/testnet-first. Autonomous real-money order execution is not implemented. Public Binance market data, backtesting, paper execution, deterministic risk controls, and AI-assisted signal review are the supported scope.

## Goals

- Consume live Binance market data for multiple symbols.
- Build a reusable feature engine (trend, momentum, volatility, volume, order-book signals).
- Keep strategy logic independent from execution.
- Add an AI Advisor that can approve/reject/flag a candidate signal, but can never bypass deterministic risk controls.
- Support backtesting and paper trading with realistic commissions/slippage assumptions.
- Expose the system through FastAPI and a React/Tauri-style dashboard.
- Preserve a clean path for research, auditing, and reproducible tests.

## Architecture

```text
Binance public market data
        |
        v
MarketData -> FeatureEngine -> Strategies -> SignalCandidate
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
                                 |           |
                               Paper       Testnet
                                 |
                                 v
                          Position/PnL Store
                                 |
                                 v
                           FastAPI/WebSocket
                                 |
                                 v
                              Dashboard
```

## Project status

Phase 1 backend is implemented: immutable domain models, deterministic risk
checks and decision history, idempotent in-memory paper fills, and health/config
endpoints. See `backend/README.md` for setup and operating limits, `CODEX_TASK.md`
for scope, and `docs/ARCHITECTURE.md` for the staged architecture.

Phase 2 adds public Binance USD-M Futures data for eight symbols, normalized
events, connection/freshness tracking, bounded subscriptions, and read-only
market-data endpoints. Depth is exposed as deltas; no local order book is built.

## Upstream attribution

This project is derived conceptually and, where later copied, code-wise from **Hinto Trader** by the Hinto contributors:

- Upstream: https://github.com/meiiie/hinto-trader
- License: MIT

The original MIT notice is preserved in `LICENSE`.

## Security

Never commit API keys, secrets, seed phrases, passwords, or 2FA codes. Secrets belong only in local environment variables and must never be exposed to the frontend or logs.
