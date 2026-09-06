# Backend

Phase 1 backend for Hinto AI Trader.

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

`/system/config` must report `real_money_execution_enabled: false` in this scaffold.

## Current components

- `src/domain/models.py` — signal, AI decision, trade intent, execution result, trading mode.
- `src/domain/execution.py` — execution gateway interface.
- `src/application/risk_engine.py` — deterministic validation and duplicate protection.
- `src/infrastructure/paper_execution.py` — in-memory simulated fills.
- `src/main.py` — FastAPI entry point.

## Next phase

Add Binance public market data only: WebSocket/REST market feeds, freshness tracking, normalized events, and multi-symbol subscriptions. No private account credentials are required for that phase.
