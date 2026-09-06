from __future__ import annotations

import os

from fastapi import FastAPI

from src.domain.models import TradingMode


app = FastAPI(title="Hinto AI Trader", version="0.1.0")


def current_mode() -> TradingMode:
    raw_mode = os.getenv("TRADING_MODE", TradingMode.PAPER.value).lower()
    try:
        return TradingMode(raw_mode)
    except ValueError:
        return TradingMode.PAPER


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/system/config")
async def system_config() -> dict[str, object]:
    mode = current_mode()
    return {
        "app": "Hinto AI Trader",
        "mode": mode.value,
        "real_money_execution_enabled": False,
        "ai_can_bypass_risk_engine": False,
    }
