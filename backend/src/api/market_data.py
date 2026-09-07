from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from src.application.market_data_hub import (
    MarketDataHub,
    MarketStatus,
    SymbolMarketSnapshot,
)


router = APIRouter(prefix="/market", tags=["market data"])


def market_data_hub(request: Request) -> MarketDataHub:
    hub = getattr(request.app.state, "market_data_hub", None)
    if hub is None:
        raise HTTPException(status_code=503, detail="Market data is not initialized")
    return hub


Hub = Annotated[MarketDataHub, Depends(market_data_hub)]


@router.get("/status", response_model=MarketStatus)
async def market_status(hub: Hub) -> MarketStatus:
    return hub.status()


@router.get("/{symbol}/latest", response_model=SymbolMarketSnapshot)
async def latest_market_data(symbol: str, hub: Hub) -> SymbolMarketSnapshot:
    try:
        return hub.latest(symbol.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown market symbol") from None
