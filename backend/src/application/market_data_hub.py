"""Latest market observations, conservative freshness, and bounded subscribers.

All methods belong to one event loop. Publication is synchronous and never waits
for consumers. Depth cache entries remain deltas, not reconstructed order books.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, TypeAdapter

from src.domain.market_data import (
    BookTickerEvent,
    ConnectionStatus,
    DepthEvent,
    EventType,
    KlineEvent,
    MarketConnectionState,
    MarketSymbol,
    NormalizedMarketEvent,
    TradeEvent,
)
from src.domain.models import DomainModel


FreshnessReason = Literal[
    "missing", "disconnected", "awaiting_recovery", "clock_skew",
    "event_stale", "receive_stale",
]


class StreamFreshness(DomainModel):
    event_type: EventType
    kline_interval: str | None = None
    stale: bool
    reason: FreshnessReason | None = None
    event_time: AwareDatetime | None = None
    received_at: AwareDatetime | None = None
    event_age_seconds: float | None = None
    receive_age_seconds: float | None = None
    connection_id: str | None = None
    connection_status: ConnectionStatus | None = None
    generation: int | None = None


class SymbolFreshness(DomainModel):
    symbol: str
    stale: bool
    last_event_at: AwareDatetime | None = None
    last_received_at: AwareDatetime | None = None
    streams: dict[str, StreamFreshness]


class SymbolMarketSnapshot(SymbolFreshness):
    as_of: AwareDatetime
    events: dict[str, NormalizedMarketEvent]


class MarketStatus(DomainModel):
    as_of: AwareDatetime
    stale_after_seconds: float
    stale: bool
    connections: tuple[MarketConnectionState, ...]
    symbols: dict[str, SymbolFreshness]
    subscriber_count: int
    dropped_events: int
    ignored_events: int


@dataclass(frozen=True)
class _CachedEvent:
    event: NormalizedMarketEvent
    connection_id: str
    generation: int
    clock_skew: bool = False


_EVENT_ADAPTER = TypeAdapter(NormalizedMarketEvent)
_SYMBOL_ADAPTER = TypeAdapter(MarketSymbol)
_TIME_ADAPTER = TypeAdapter(AwareDatetime)


class MarketEventQueue(asyncio.Queue[NormalizedMarketEvent]):
    """A normal observation queue with loss accounting local to its subscriber."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self._dropped_events = 0

    @property
    def dropped_events(self) -> int:
        return self._dropped_events


class MarketDataHub:
    def __init__(
        self,
        symbols: Sequence[str],
        *,
        stale_after_seconds: float = 10,
        kline_intervals: Sequence[str] = ("1m",),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if isinstance(symbols, str) or not symbols:
            raise ValueError("symbols must be a nonempty sequence")
        normalized = tuple(_SYMBOL_ADAPTER.validate_python(s.upper()) for s in symbols)
        if len(set(normalized)) != len(normalized):
            raise ValueError("symbols must be unique")
        if (isinstance(stale_after_seconds, bool)
                or not isinstance(stale_after_seconds, (int, float))
                or not math.isfinite(stale_after_seconds) or stale_after_seconds <= 0):
            raise ValueError("stale_after_seconds must be finite and positive")
        if isinstance(kline_intervals, str) or not kline_intervals:
            raise ValueError("kline_intervals must be a nonempty sequence")
        interval_adapter = TypeAdapter(KlineEvent.model_fields["interval"].rebuild_annotation())
        intervals = tuple(interval_adapter.validate_python(item) for item in kline_intervals)
        if len(set(intervals)) != len(intervals):
            raise ValueError("kline_intervals must be unique")
        self.symbols = normalized
        self.stale_after_seconds = float(stale_after_seconds)
        self.kline_intervals = intervals
        self._clock = clock
        self._expected = {
            **{kind.value: (kind, None) for kind in EventType if kind != EventType.KLINE},
            **{f"kline:{interval}": (EventType.KLINE, interval) for interval in intervals},
        }
        self._latest: dict[str, dict[str, _CachedEvent]] = {symbol: {} for symbol in normalized}
        # Bad clocks remain visible in latest, but cannot poison event ordering.
        self._ordering: dict[str, dict[str, _CachedEvent]] = {symbol: {} for symbol in normalized}
        self._connections: dict[str, MarketConnectionState] = {}
        self._event_connections: dict[EventType, str] = {}
        self._subscribers: set[MarketEventQueue] = set()
        self._dropped_events = 0
        self._ignored_events = 0

    def update_connection(self, state: MarketConnectionState) -> None:
        state = MarketConnectionState.model_validate(state)
        previous = self._connections.get(state.connection_id)
        if previous is not None and (
            state.generation < previous.generation
            or (state.generation == previous.generation and state.changed_at < previous.changed_at)
        ):
            return
        self._connections[state.connection_id] = state
        for event_type in state.event_types:
            self._event_connections[event_type] = state.connection_id

    def publish(self, event: NormalizedMarketEvent, *, connection_id: str) -> None:
        event = _EVENT_ADAPTER.validate_python(event)
        key = f"kline:{event.interval}" if isinstance(event, KlineEvent) else event.event_type.value
        state = self._connections.get(connection_id)
        if (event.symbol not in self._latest or key not in self._expected
                or state is None or state.status != ConnectionStatus.CONNECTED
                or event.event_type not in state.event_types
                or self._event_connections.get(event.event_type) != connection_id):
            self._ignored_events += 1
            return
        now = _TIME_ADAPTER.validate_python(self._clock())
        previous = self._ordering[event.symbol].get(key)
        if previous is not None and (
            previous.event.event_time > now or previous.event.received_at > now
        ):
            previous = None  # A local clock rollback also invalidates its ordering reference.
        changed_generation = previous is not None and (
            previous.connection_id != connection_id or previous.generation != state.generation
        )
        if previous is not None and not self._advances(
            event, previous.event, allow_sequence_reset=changed_generation,
        ):
            self._ignored_events += 1
            return
        cached = _CachedEvent(
            event, connection_id, state.generation,
            clock_skew=event.event_time > now or event.received_at > now,
        )
        self._latest[event.symbol][key] = cached
        if not cached.clock_skew:
            self._ordering[event.symbol][key] = cached
        else:
            # Keep diagnostics visible, but never let a queued future observation
            # become admissible history merely because a slow consumer catches up.
            return
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
                queue.task_done()
                queue._dropped_events += 1
                self._dropped_events += 1
            queue.put_nowait(event)

    @staticmethod
    def _advances(
        event: NormalizedMarketEvent, previous: NormalizedMarketEvent,
        *, allow_sequence_reset: bool = False,
    ) -> bool:
        if event.event_time < previous.event_time:
            return False
        # A new connection generation may restart IDs, but only a strictly newer
        # exchange observation can establish that baseline. This does not verify
        # sequence continuity or recover depth updates missed while disconnected.
        sequence_reset = allow_sequence_reset and event.event_time > previous.event_time
        if isinstance(event, TradeEvent) and isinstance(previous, TradeEvent):
            return sequence_reset or event.aggregate_trade_id > previous.aggregate_trade_id
        if isinstance(event, BookTickerEvent) and isinstance(previous, BookTickerEvent):
            return sequence_reset or event.update_id > previous.update_id
        if isinstance(event, DepthEvent) and isinstance(previous, DepthEvent):
            return sequence_reset or event.final_update_id > previous.final_update_id
        if isinstance(event, KlineEvent) and isinstance(previous, KlineEvent):
            if event.open_time < previous.open_time:
                return False
            if event.open_time == previous.open_time and (
                event.trade_count < previous.trade_count
                or (previous.is_closed and not event.is_closed)
            ):
                return False
            if event.event_time == previous.event_time:
                return event.open_time > previous.open_time or (
                    event.trade_count > previous.trade_count
                    or (event.is_closed and not previous.is_closed)
                )
        return event.event_time > previous.event_time

    @contextmanager
    def subscribe(self, max_queue_size: int = 100) -> Iterator[MarketEventQueue]:
        """Yield a bounded queue; drop its oldest item when its consumer is slow.

        These subscriptions are lossy observations, unsuitable for reconstructing
        an order book or an audit log. Overflow is counted in status.dropped_events
        and in queue.dropped_events for consumers that must invalidate history.
        Clock-skewed diagnostic observations remain in latest but aren't queued.
        Context exit always unsubscribes, including exceptions and cancellation.
        """
        if isinstance(max_queue_size, bool) or not isinstance(max_queue_size, int) or max_queue_size < 1:
            raise ValueError("max_queue_size must be a positive integer")
        queue = MarketEventQueue(maxsize=max_queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def status(self) -> MarketStatus:
        now = _TIME_ADAPTER.validate_python(self._clock())
        symbols = {symbol: self._symbol_freshness(symbol, now) for symbol in self.symbols}
        return MarketStatus(
            as_of=now, stale_after_seconds=self.stale_after_seconds,
            stale=any(state.stale for state in symbols.values()),
            connections=tuple(self._connections.values()), symbols=symbols,
            subscriber_count=len(self._subscribers), dropped_events=self._dropped_events,
            ignored_events=self._ignored_events,
        )

    def latest(self, symbol: str) -> SymbolMarketSnapshot:
        symbol = symbol.upper()
        if symbol not in self._latest:
            raise KeyError(symbol)
        now = _TIME_ADAPTER.validate_python(self._clock())
        state = self._symbol_freshness(symbol, now)
        return SymbolMarketSnapshot(
            **state.model_dump(), as_of=now,
            events={key: cached.event for key, cached in self._latest[symbol].items()},
        )

    def _symbol_freshness(self, symbol: str, now: datetime) -> SymbolFreshness:
        streams = {
            key: self._stream_freshness(self._latest[symbol].get(key), kind, interval, now)
            for key, (kind, interval) in self._expected.items()
        }
        return SymbolFreshness(
            symbol=symbol, stale=any(stream.stale for stream in streams.values()),
            last_event_at=max((item.event.event_time for item in self._latest[symbol].values()), default=None),
            last_received_at=max((item.event.received_at for item in self._latest[symbol].values()), default=None),
            streams=streams,
        )

    def _stream_freshness(
        self, cached: _CachedEvent | None, kind: EventType,
        interval: str | None, now: datetime,
    ) -> StreamFreshness:
        connection_id = self._event_connections.get(kind)
        connection = self._connections.get(connection_id) if connection_id is not None else None
        event = cached.event if cached is not None else None
        event_age = (now - event.event_time).total_seconds() if event is not None else None
        receive_age = (now - event.received_at).total_seconds() if event is not None else None
        reason: FreshnessReason | None = None
        if cached is None:
            reason = "missing"
        elif connection is None or connection.status != ConnectionStatus.CONNECTED:
            reason = "disconnected"
        elif cached.connection_id != connection_id or cached.generation != connection.generation:
            reason = "awaiting_recovery"
        elif event_age is not None and receive_age is not None:
            if cached.clock_skew or event_age < 0 or receive_age < 0:
                reason = "clock_skew"
            elif event_age >= self.stale_after_seconds:
                reason = "event_stale"
            elif receive_age >= self.stale_after_seconds:
                reason = "receive_stale"
        return StreamFreshness(
            event_type=kind, kline_interval=interval, stale=reason is not None, reason=reason,
            event_time=event.event_time if event is not None else None,
            received_at=event.received_at if event is not None else None,
            event_age_seconds=event_age, receive_age_seconds=receive_age,
            connection_id=connection_id,
            connection_status=connection.status if connection is not None else None,
            generation=cached.generation if cached is not None else None,
        )
