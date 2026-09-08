"""One-loop, process-local feature history and freshness-aware snapshot service."""

import asyncio
from datetime import datetime, timedelta

from src.application.feature_calculations import calculate_group
from src.application.feature_history import FeatureHistory, next_open_time
from src.application.feature_settings import FeatureSettings
from src.application.market_data_hub import MarketDataHub, MarketEventQueue, SymbolMarketSnapshot
from src.domain.features import (
    FeatureEngineStatus, FeatureGroup, FeatureSnapshot, FeatureSource,
    FeatureSymbolStatus, NamedGroupStatus, Readiness,
)
from src.domain.market_data import ConnectionStatus, KlineEvent, NormalizedMarketEvent


GROUPS = ("trade", "returns", "trend", "momentum", "volatility", "volume",
          "microstructure", "mark_funding", "regime")
CONTEXT_STREAMS = {"trade": "trade", "microstructure": "book_ticker", "mark_funding": "mark_price"}
GROUP_MODELS = {name: FeatureSnapshot.model_fields[name].annotation for name in GROUPS}


class FeatureEngine:
    def __init__(self, hub: MarketDataHub, settings: FeatureSettings | None = None,
                 *, interval: str | None = None, max_queue_size: int = 1000) -> None:
        if type(max_queue_size) is not int or max_queue_size < 1:
            raise ValueError("max_queue_size must be a positive integer")
        self.hub = hub
        self.settings = settings if settings is not None else FeatureSettings()
        self.interval = interval if interval is not None else hub.kline_intervals[0]
        if self.interval not in hub.kline_intervals:
            raise ValueError("feature interval must be supplied by the market hub")
        self._queue_size = max_queue_size
        self._histories = {symbol: FeatureHistory(symbol, self.interval, self.settings.history_limit)
                           for symbol in hub.symbols}
        self._queue: MarketEventQueue | None = None
        self._connection: tuple[str, int, ConnectionStatus] | None = None
        self._last_now: datetime | None = None
        self._drops = 0
        self._failure: str | None = None
        self.running = False
        config = self.settings
        self._required = {
            "trade": 1, "microstructure": 1, "mark_funding": 1,
            "returns": max(2, config.rolling_return_windows[-1] + 1),
            "trend": config.ema_long,
            "momentum": max(config.rsi_period + 1, config.roc_period + 1),
            "volatility": max(config.atr_period, config.volatility_window + 1),
            "volume": max(config.vwap_window, config.relative_volume_window + 1),
            "regime": max(config.ema_slow, config.atr_period, config.roc_period + 1,
                          config.relative_volume_window + 1),
        }

    async def run(self) -> None:
        """Subscribe before the first await; cancellation always unsubscribes."""
        if self.running:
            raise RuntimeError("feature engine is already running")
        self._failure = None
        with self.hub.subscribe(self._queue_size) as queue:
            self._queue = queue
            self._drops = 0
            self._connection = None
            self._last_now = None
            self.running = True
            try:
                self._synchronize()
                while True:
                    event = await queue.get()
                    try:
                        if isinstance(event, KlineEvent) and not self._synchronize():
                            self._consume(event)
                    finally:
                        queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Expose a stable diagnostic, never arbitrary exception text.
                self._failure = "engine_failed"
            finally:
                self._discard_pending()
                for history in self._histories.values():
                    history.reset(self._failure or "engine_stopped")
                self.running = False
                self._queue = None

    def _discard_pending(self) -> None:
        if self._queue is not None:
            while not self._queue.empty():
                self._queue.get_nowait()
                self._queue.task_done()

    def _synchronize(self) -> bool:
        """An untagged queued observation cannot establish reconnect continuity.

        Drain on transitions/loss, then seed at most one current closed bar per
        symbol. The Hub cache supplies verified current-generation provenance.
        """
        if self._queue is None:
            return False
        status = self.hub.status()
        clock_rollback = self._last_now is not None and status.as_of < self._last_now
        self._last_now = status.as_of
        stream = status.symbols[self.hub.symbols[0]].streams[f"kline:{self.interval}"]
        connection = next((state for state in status.connections
                           if state.connection_id == stream.connection_id), None)
        token = None if connection is None else (connection.connection_id, connection.generation, connection.status)
        lost = self._queue.dropped_events != self._drops
        if token == self._connection and not lost and not clock_rollback:
            return False
        self._connection = token
        self._drops = self._queue.dropped_events
        self._discard_pending()
        for history in self._histories.values():
            history.reset("clock_rollback" if clock_rollback else "subscriber_gap" if lost else "connection_changed")
            snapshot = self.hub.latest(history.symbol)
            key = f"kline:{self.interval}"
            freshness = snapshot.streams[key]
            event = snapshot.events.get(key)
            if (connection is not None and connection.status == ConnectionStatus.CONNECTED
                    and not freshness.stale and freshness.generation == connection.generation
                    and isinstance(event, KlineEvent) and event.is_closed):
                history.accept(event, now=snapshot.as_of)
        return True

    def _consume(self, event: NormalizedMarketEvent) -> None:
        if isinstance(event, KlineEvent) and event.interval == self.interval:
            snapshot = self.hub.latest(event.symbol)
            self._histories[event.symbol].accept(event, now=snapshot.as_of)

    def _refresh(self) -> None:
        self._synchronize()
        if self._queue is not None:
            # Synchronous reads cannot race the consumer on this same event loop.
            while not self._queue.empty():
                event = self._queue.get_nowait()
                try:
                    self._consume(event)
                finally:
                    self._queue.task_done()

    def latest(self, symbol: str) -> FeatureSnapshot:
        symbol = symbol.strip().upper()
        if symbol not in self._histories:
            raise KeyError(symbol)
        self._refresh()
        snapshot = self.hub.latest(symbol)
        history = self._histories[symbol]
        groups = {name: self._group(name, snapshot, history) for name in GROUPS}
        states = {group.state for group in groups.values()}
        if states == {Readiness.READY}:
            readiness = Readiness.READY
        elif Readiness.READY in states:
            readiness = Readiness.PARTIAL
        elif Readiness.STALE in states:
            readiness = Readiness.STALE
        elif Readiness.WARMING_UP in states:
            readiness = Readiness.WARMING_UP
        else:
            readiness = Readiness.UNAVAILABLE
        keys = ("trade", f"kline:{self.interval}", "book_ticker", "mark_price")
        return FeatureSnapshot(
            symbol=symbol, generated_at=snapshot.as_of, interval=self.interval,
            state=readiness,
            reasons=tuple(f"{name}:{reason}" for name, group in groups.items() for reason in group.reasons),
            sources=tuple(FeatureSource(stream=key, **snapshot.streams[key].model_dump(include={
                "event_time", "received_at", "stale", "reason", "connection_id", "generation",
            })) for key in keys),
            closed_candle_time=history.closed[-1].close_time if history.closed else None,
            closed_candles=len(history.closed), history_resets=history.resets,
            last_history_reset=history.last_reset, **groups,
        )

    def _group(self, name: str, snapshot: SymbolMarketSnapshot, history: FeatureHistory) -> FeatureGroup:
        key = CONTEXT_STREAMS.get(name, f"kline:{self.interval}")
        stream = snapshot.streams[key]
        event = snapshot.events.get(key)
        candles = history.closed
        available = int(event is not None) if name in CONTEXT_STREAMS else len(candles)
        arguments = dict(required_samples=self._required[name], available_samples=available)

        def absent(state: Readiness, *reasons: str) -> FeatureGroup:
            return GROUP_MODELS[name](state=state, reasons=tuple(reasons), **arguments)

        if self._failure:
            return absent(Readiness.UNAVAILABLE, self._failure)
        if stream.stale:
            state = Readiness.UNAVAILABLE if stream.reason == "missing" else Readiness.STALE
            return absent(state, f"{key}:{stream.reason}")
        if name not in CONTEXT_STREAMS:
            if isinstance(event, KlineEvent):
                try:
                    end = next_open_time(event.open_time, self.interval)
                except ValueError:
                    return absent(Readiness.UNAVAILABLE, "invalid_candle_time")
                if event.is_closed and (end > event.event_time or event.close_time > event.event_time):
                    return absent(Readiness.UNAVAILABLE, "invalid_candle_time")
            if candles:
                try:
                    deadline = next_open_time(next_open_time(candles[-1].open_time, self.interval), self.interval)
                    expired = snapshot.as_of >= deadline + timedelta(seconds=self.hub.stale_after_seconds)
                except (ValueError, OverflowError):
                    return absent(Readiness.UNAVAILABLE, "invalid_candle_time")
                if expired:
                    return absent(Readiness.STALE, "closed_history_stale")
            if available < self._required[name]:
                reasons = ("insufficient_history",) + ((history.last_reset,) if history.last_reset else ())
                return absent(Readiness.WARMING_UP, *reasons)
        values = calculate_group(name, candles, self.settings, event=event, now=snapshot.as_of)
        if values is None:
            return absent(Readiness.UNAVAILABLE, "invalid_numeric_input")
        return GROUP_MODELS[name](state=Readiness.READY, values=values, **arguments)

    def status(self) -> FeatureEngineStatus:
        snapshots = tuple(self.latest(symbol) for symbol in self.hub.symbols)
        return FeatureEngineStatus(
            generated_at=self.hub.status().as_of, running=self.running,
            interval=self.interval, history_limit=self.settings.history_limit,
            symbols=tuple(FeatureSymbolStatus(
                symbol=snapshot.symbol, state=snapshot.state, closed_candles=snapshot.closed_candles,
                history_resets=snapshot.history_resets, last_history_reset=snapshot.last_history_reset,
                groups=tuple(NamedGroupStatus(name=name, **getattr(snapshot, name).model_dump(exclude={"values"}))
                             for name in GROUPS),
            ) for snapshot in snapshots),
        )
