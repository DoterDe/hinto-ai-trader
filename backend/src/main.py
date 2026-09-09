from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI

from src.api.features import router as features_router
from src.api.market_data import router as market_data_router
from src.api.strategies import router as strategies_router
from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.market_data_hub import MarketDataHub
from src.application.strategy_engine import StrategyEngine
from src.application.strategy_settings import StrategySettings
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
    feature_settings: FeatureSettings | None = None,
    strategy_settings: StrategySettings | None = None,
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
        features = FeatureEngine(hub, feature_settings)
        application.state.feature_engine = features
        application.state.strategy_engine = StrategyEngine(features, strategy_settings, symbols=config.symbols)
        feed = source if source is not None else BinancePublicMarketData(config)
        # A disabled feed needs no consumer. Injected offline sources still run.
        feature_task = None
        if config.enabled or source is not None:
            feature_task = asyncio.create_task(features.run(), name="feature-engine")
        application.state.feature_engine_task = feature_task
        task = None
        try:
            # Register the consumer before the feed can publish its first event.
            if feature_task is not None:
                await asyncio.sleep(0)
            task = asyncio.create_task(_run_market_data(feed, hub), name="market-data")
            application.state.market_data_task = task
            # Allow initial disabled/connecting state to be visible immediately.
            await asyncio.sleep(0)
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if feature_task is not None:
                feature_task.cancel()
                with suppress(asyncio.CancelledError):
                    await feature_task

    application = FastAPI(title="Hinto AI Trader", version="0.1.0", lifespan=lifespan)
    application.include_router(market_data_router)
    application.include_router(features_router)
    application.include_router(strategies_router)
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
