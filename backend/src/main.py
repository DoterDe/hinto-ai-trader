from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI

from src.api.market_data import router as market_data_router
from src.application.market_data_hub import MarketDataHub
from src.domain.market_data import (
    ConnectionStatus,
    EventType,
    MarketConnectionState,
    MarketDataSource,
)
from src.domain.models import TradingMode
from src.infrastructure.binance.public_market_data import BinancePublicMarketData
from src.infrastructure.binance.settings import MarketDataSettings


def _stop_connections(hub: MarketDataHub, reason: str) -> None:
    """Expose safe lifecycle reasons even if an injected source fails early."""
    now = datetime.now(timezone.utc)
    states = hub.status().connections
    if not states:
        states = (
            MarketConnectionState(
                connection_id="source",
                event_types=tuple(EventType),
                status=ConnectionStatus.STOPPED,
                changed_at=now,
            ),
        )
    for state in states:
        if state.status != ConnectionStatus.DISABLED:
            hub.update_connection(
                state.model_copy(update={
                    "status": ConnectionStatus.STOPPED,
                    "changed_at": now,
                    "reason": reason,
                })
            )


async def _run_market_data(source: MarketDataSource, hub: MarketDataHub) -> None:
    try:
        await source.run(hub)
    except asyncio.CancelledError:
        _stop_connections(hub, "shutdown")
        raise
    except Exception:
        # Exception text may contain remote URLs or library internals.
        _stop_connections(hub, "source_failed")
    else:
        _stop_connections(hub, "source_stopped")


def create_app(
    settings: MarketDataSettings | None = None,
    source: MarketDataSource | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Importing the app has no side effects; environment is read at startup.
        config = settings if settings is not None else MarketDataSettings()
        hub = MarketDataHub(
            config.symbols,
            stale_after_seconds=config.stale_after_seconds,
            kline_intervals=(config.kline_interval,),
        )
        application.state.market_data_hub = hub
        feed = source if source is not None else BinancePublicMarketData(config)
        task = asyncio.create_task(_run_market_data(feed, hub), name="market-data")
        application.state.market_data_task = task
        try:
            # Allow initial disabled/connecting state to be visible immediately.
            await asyncio.sleep(0)
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application = FastAPI(title="Hinto AI Trader", version="0.1.0", lifespan=lifespan)
    application.include_router(market_data_router)
    application.add_api_route("/health", health, methods=["GET"])
    application.add_api_route("/system/config", system_config, methods=["GET"])
    return application


def current_mode() -> TradingMode:
    raw_mode = os.getenv("TRADING_MODE", TradingMode.PAPER.value).lower()
    try:
        return TradingMode(raw_mode)
    except ValueError:
        return TradingMode.PAPER


async def health() -> dict[str, str]:
    return {"status": "ok"}


async def system_config() -> dict[str, object]:
    mode = current_mode()
    return {
        "app": "Hinto AI Trader",
        "mode": mode.value,
        "real_money_execution_enabled": False,
        "ai_can_bypass_risk_engine": False,
    }


app = create_app()
