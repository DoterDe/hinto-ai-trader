"""Finite historical replay through the unchanged production analytical engines."""

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone

from src.application.decision_engine import DecisionEngine
from src.application.decision_settings import DecisionSettings
from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.historical_bars import ordered_bars, symbols_for_replay
from src.application.market_data_hub import MarketDataHub
from src.application.strategy_engine import StrategyEngine
from src.application.strategy_settings import StrategySettings
from src.domain.backtesting import HistoricalDecision
from src.domain.features import FeatureSnapshot
from src.domain.market_data import ConnectionStatus, EventType, KlineEvent, MarketConnectionState
from src.domain.strategies import StrategySnapshot
from src.strategies.identity import identity


class ReplayClock:
    def __init__(self, timestamp: datetime) -> None:
        self._now: datetime | None = None
        self.advance(timestamp)

    def advance(self, timestamp: datetime) -> None:
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("replay clock requires an aware datetime")
        timestamp = timestamp.astimezone(timezone.utc)
        if self._now is not None and timestamp < self._now:
            raise ValueError("replay clock cannot move backwards")
        self._now = timestamp

    def __call__(self) -> datetime:
        return self._now


@dataclass(frozen=True)
class ReplayFrame:
    """Transient diagnostics; the runner retains only HistoricalDecision."""

    bar: KlineEvent
    features: FeatureSnapshot
    strategy: StrategySnapshot
    observation: HistoricalDecision


class DecisionCapture:
    """Run-local O(unique decisions) dedupe; conflicting ID reuse is an error."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self.duplicate_reads = 0

    def add(self, observation: HistoricalDecision) -> bool:
        observation = HistoricalDecision.model_validate(observation)
        decision = observation.decision
        # Read-time ages/reasons/full snapshot IDs can vary for the same identity.
        stable = decision.model_dump(exclude={"generated_at", "source_strategy_timestamp",
            "source_feature_timestamp", "strategy_snapshot_id", "reasons", "readiness"})
        fingerprint = identity("capture", (stable, observation.source_bar_open_time,
                                            observation.source_bar_close_time))
        previous = self._seen.get(decision.decision_id)
        if previous is not None:
            if previous != fingerprint:
                raise ValueError("conflicting historical decision identity")
            self.duplicate_reads += 1
            return False
        self._seen[decision.decision_id] = fingerprint
        return True


class HistoricalReplay:
    def __init__(self, *, symbols: Sequence[str], interval: str = "1m",
                 feature_settings: FeatureSettings | None = None,
                 strategy_settings: StrategySettings | None = None,
                 decision_settings: DecisionSettings | None = None) -> None:
        self.symbols = symbols_for_replay(symbols)
        self.interval = interval
        # FeatureSettings predates always-revalidate: reconstruct its public fields.
        self.feature_settings = FeatureSettings.model_validate(feature_settings.model_dump()) if feature_settings is not None else FeatureSettings()
        self.strategy_settings = StrategySettings.model_validate(strategy_settings) if strategy_settings is not None else StrategySettings()
        self.decision_settings = DecisionSettings.model_validate(decision_settings) if decision_settings is not None else DecisionSettings()

    async def frames(self, bars: Iterable[KlineEvent]) -> AsyncIterator[ReplayFrame]:
        """Use aclosing() if stopping consumption early; full exhaustion cleans up.

        No sleep follows historical elapsed time. The single startup yield registers
        FeatureEngine; latest() then drains each published event synchronously.
        Periodic zero-delay yields permit cancellation without changing replay time.
        """
        iterator = ordered_bars(bars, symbols=self.symbols, interval=self.interval)
        first = next(iterator, None)
        if first is None:
            return
        clock = ReplayClock(first.event_time)
        hub = MarketDataHub(self.symbols, kline_intervals=(self.interval,), clock=clock)
        hub.update_connection(MarketConnectionState(connection_id="historical_replay",
            event_types=(EventType.KLINE,), status=ConnectionStatus.CONNECTED,
            changed_at=clock(), generation=1))
        features = FeatureEngine(hub, self.feature_settings, interval=self.interval)
        strategies = StrategyEngine(features, self.strategy_settings, symbols=self.symbols, clock=clock)
        decisions = DecisionEngine(strategies, self.decision_settings, symbols=self.symbols, clock=clock)
        task = asyncio.create_task(features.run(), name="historical-feature-engine")
        try:
            await asyncio.sleep(0)
            if not features.running:
                raise RuntimeError("historical feature consumer failed to start")
            event, count = first, 0
            while event is not None:
                clock.advance(event.event_time)
                hub.publish(event, connection_id="historical_replay")
                snapshot = features.latest(event.symbol)
                if snapshot.closed_candle_time != event.close_time or not features.running:
                    raise RuntimeError("historical feature consumer did not accept the finalized bar")
                strategy = strategies.evaluate(snapshot, now=clock())
                decision = decisions.evaluate(strategy, now=clock())
                observation = HistoricalDecision(source_bar_open_time=event.open_time,
                    source_bar_close_time=event.close_time, decision=decision, regime=snapshot.regime.values)
                yield ReplayFrame(event, snapshot, strategy, observation)
                count += 1
                if count % 128 == 0:
                    await asyncio.sleep(0)
                event = next(iterator, None)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            iterator.close()
