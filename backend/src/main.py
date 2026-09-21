from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from src.api.decisions import router as decisions_router
from src.api.features import router as features_router
from src.api.market_data import router as market_data_router
from src.api.strategies import router as strategies_router
from src.api.live_paper import router as live_paper_router
from src.api.validation import router as validation_router
from src.application.validation_telemetry import load_validation
from src.application.decision_engine import DecisionEngine
from src.application.decision_settings import DecisionSettings
from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.backtest_settings import BacktestSettings
from src.application.live_paper_clock import LiveClock, SystemLiveClock
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.domain.live_paper import LivePaperStatus
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
    now = hub.status().as_of
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
    decision_settings: DecisionSettings | None = None,
    live_paper_settings: LivePaperSettings | None = None,
    portfolio_settings: PaperPortfolioSettings | None = None,
    backtest_settings: BacktestSettings | None = None,
    clock: LiveClock | None = None,
    persistence_settings: PaperPersistenceSettings | None = None,
    validation_report_path: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Importing the app has no side effects; environment is read at startup.
        application.state.validation_snapshot = load_validation(
            validation_report_path if validation_report_path is not None else os.getenv("VALIDATION_REPORT_PATH"))
        config = settings if settings is not None else MarketDataSettings()
        runtime_clock = clock or SystemLiveClock()
        hub = MarketDataHub(
            config.symbols,
            stale_after_seconds=config.stale_after_seconds,
            kline_intervals=(config.kline_interval,),
            clock=runtime_clock.now,
        )
        application.state.market_data_hub = hub
        features = FeatureEngine(hub, feature_settings)
        application.state.feature_engine = features
        application.state.strategy_engine = StrategyEngine(features, strategy_settings, symbols=config.symbols, clock=runtime_clock.now)
        application.state.decision_engine = DecisionEngine(
            application.state.strategy_engine, decision_settings, symbols=config.symbols, clock=runtime_clock.now)
        paper_config = live_paper_settings if live_paper_settings is not None else LivePaperSettings()
        # A disabled public source cannot support a live paper consumer. Injected
        # local sources still exercise the enabled runtime in offline tests.
        if not config.enabled and source is None:
            paper_config = LivePaperSettings.model_validate(paper_config.model_copy(update={'enabled': False}))
        paper = LivePaperCoordinator(hub, settings=paper_config, portfolio_settings=portfolio_settings,
            costs=backtest_settings, feature_settings=feature_settings, strategy_settings=strategy_settings,
            decision_settings=decision_settings, clock=runtime_clock, persistence_settings=persistence_settings)
        application.state.live_paper_coordinator = paper
        feed = source if source is not None else BinancePublicMarketData(config)
        # A disabled feed needs no consumer. Injected offline sources still run.
        feature_task = None
        if config.enabled or source is not None:
            feature_task = asyncio.create_task(features.run(), name="feature-engine")
        application.state.feature_engine_task = feature_task
        paper_task = None
        application.state.live_paper_task = None
        task = None
        try:
            # Recovery completes before any public source can publish. Failures
            # leave read-only diagnostics available and the paper runtime halted.
            recovered = True
            if paper_config.enabled:
                recovered = await paper.persistence.start(paper)
                if not recovered:
                    paper._status = LivePaperStatus.ERROR
                    paper._last_problem = paper.persistence.state.reason
            # Register the consumer before the feed can publish its first event.
            if feature_task is not None:
                await asyncio.sleep(0)
            if paper_config.enabled and recovered:
                paper_task = asyncio.create_task(paper.run(), name='live-paper-coordinator')
                application.state.live_paper_task = paper_task
                await asyncio.sleep(0)
            if recovered:
                task = asyncio.create_task(_run_market_data(feed, hub), name="market-data")
            application.state.market_data_task = task
            # Allow initial disabled/connecting state to be visible immediately.
            await asyncio.sleep(0)
            yield
        finally:
            # Freeze the durable consumer before the source publishes STOPPED;
            # shutdown is not evidence that a future holding candle was missed.
            if paper.persistence.settings.enabled and paper_task is not None:
                paper_task.cancel()
                with suppress(asyncio.CancelledError):
                    await paper_task
                paper_task = None
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if paper_task is not None:
                paper_task.cancel()
                with suppress(asyncio.CancelledError):
                    await paper_task
            if feature_task is not None:
                feature_task.cancel()
                with suppress(asyncio.CancelledError):
                    await feature_task
            await paper.persistence.close()

    application = FastAPI(title="Hinto AI Trader", version="0.1.0", lifespan=lifespan)
    application.include_router(market_data_router)
    application.include_router(features_router)
    application.include_router(strategies_router)
    application.include_router(decisions_router)
    application.include_router(live_paper_router)
    application.include_router(validation_router)
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
