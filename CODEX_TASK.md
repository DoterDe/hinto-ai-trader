# Current Codex Task — Phase 1

Read `AGENTS.md` first.

## Objective
Create the first runnable backend scaffold for Hinto AI Trader without autonomous real-money execution.

## Required implementation
1. FastAPI app with `/health` and `/system/config`.
2. Domain models:
   - `SignalCandidate`
   - `AIDecision`
   - `TradeIntent`
   - `ApprovedTradeIntent`
3. Deterministic `RiskEngine` that rejects stale signals, invalid confidence/size, disabled execution, and duplicate signal IDs.
4. `ExecutionGateway` protocol/ABC.
5. `PaperExecutionGateway` that records simulated fills locally in memory for now.
6. `TradingMode` limited to `PAPER` and `TESTNET`.
7. Unit tests for the risk engine and paper executor.
8. `.env.example` with no secrets and paper mode by default.

## Do not do in Phase 1
- Do not implement real-money/live execution.
- Do not add private Binance account credentials.
- Do not add an LLM provider yet; only define the interface/models.
- Do not copy large upstream Hinto modules blindly.

## Commands to run
```bash
cd backend
python -m pytest
uvicorn src.main:app --reload
```

## Completion report
Summarize:
- files changed
- tests executed
- architectural decisions
- any blockers
