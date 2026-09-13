"""Closed-bar-only view using unchanged analytical engines, never latest live cache.

Only externally admitted public bars enter this view. Canonical close time is the
analytical clock; real publication/receipt freshness is enforced by the coordinator.
Optional book context stays absent instead of reading a post-close quote.
"""

import asyncio
from contextlib import suppress
from datetime import datetime

from src.application.decision_engine import DecisionEngine
from src.application.decision_settings import DecisionSettings
from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.historical_replay import ReplayClock
from src.application.market_data_hub import MarketDataHub
from src.application.strategy_engine import StrategyEngine
from src.application.strategy_settings import StrategySettings
from src.domain.features import FeatureSnapshot
from src.domain.decisions import DecisionRecord
from src.domain.market_data import ConnectionStatus, EventType, KlineEvent, MarketConnectionState
from src.domain.strategies import StrategySnapshot


class LivePaperAnalysis:
    def __init__(self, symbols: tuple[str, ...], interval: str, feature_settings: FeatureSettings,
                 strategy_settings: StrategySettings, decision_settings: DecisionSettings,
                 stale_after_seconds: float) -> None:
        self.symbols, self.interval = symbols, interval
        self.feature_settings = feature_settings
        self.strategy_settings = strategy_settings
        self.decision_settings = decision_settings
        self.stale_after_seconds = stale_after_seconds
        self.task: asyncio.Task | None = None
        self.hub: MarketDataHub | None = None
        self.features: FeatureEngine | None = None

    async def start(self, boundary: datetime) -> None:
        if self.task is not None:
            return
        self.clock = ReplayClock(boundary)
        self.hub = MarketDataHub(self.symbols, kline_intervals=(self.interval,), clock=self.clock,
                                 stale_after_seconds=self.stale_after_seconds)
        self.features = FeatureEngine(self.hub, self.feature_settings)
        self.strategies = StrategyEngine(self.features, self.strategy_settings, symbols=self.symbols, clock=self.clock)
        self.decisions = DecisionEngine(self.strategies, self.decision_settings, symbols=self.symbols, clock=self.clock)
        self.task = asyncio.create_task(self.features.run(), name='live-paper-features')
        await asyncio.sleep(0)
        if not self.features.running:
            raise RuntimeError('closed-bar features failed to start')

    def evaluate(self, boundary: datetime, bars: tuple[KlineEvent, ...], generation: int
                 ) -> tuple[tuple[FeatureSnapshot, StrategySnapshot, DecisionRecord], ...]:
        if self.task is None or self.task.done() or not self.features.running:
            raise RuntimeError('closed-bar features are unavailable')
        self.clock.advance(boundary)
        self.hub.update_connection(MarketConnectionState(connection_id='live_closed_bars',
            event_types=(EventType.KLINE,), status=ConnectionStatus.CONNECTED,
            changed_at=boundary, generation=generation))
        for bar in bars:
            self.hub.publish(bar, connection_id='live_closed_bars')
        result = []
        for bar in bars:
            snapshot = self.features.latest(bar.symbol)
            if snapshot.closed_candle_time != bar.close_time:
                raise RuntimeError('closed-bar feature history did not accept bar')
            strategy = self.strategies.evaluate(snapshot, now=boundary)
            decision = self.decisions.evaluate(strategy, now=boundary)
            result.append((snapshot, strategy, decision))
        return tuple(result)

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
