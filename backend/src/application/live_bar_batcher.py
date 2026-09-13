"""Pure bounded finalized-bar grouping with explicit wall/monotonic clocks.

No async task or timer is created here. The coordinator calls push/poll using its
injected timer. The finalized watermark permanently prevents historical rewrites.
"""

import math
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.application.feature_history import next_open_time
from src.application.historical_bars import symbols_for_replay, validate_bar
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_portfolio_policy import aware
from src.domain.live_paper import LiveBarBatch
from src.domain.market_data import KlineEvent
from src.strategies.identity import identity


def canonical_bar(event: KlineEvent) -> KlineEvent:
    """Validate OHLCV/grid via Phase 6; normalize only bar-availability timestamps.

    The caller retains original publication/receipt times for admission freshness
    checks. This function cannot make a stale observation admissible.
    """
    event = KlineEvent.model_validate(event)
    end = next_open_time(event.open_time, event.interval)
    return validate_bar(event.model_copy(update={"event_time": end, "received_at": end}))


@dataclass(frozen=True)
class BatchNotice:
    reason: str
    symbol: str | None = None
    boundary: datetime | None = None


@dataclass(frozen=True)
class BatchResult:
    batches: tuple[LiveBarBatch, ...] = ()
    notices: tuple[BatchNotice, ...] = ()


@dataclass
class _Pending:
    deadline: float
    bars: dict[str, KlineEvent] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    conflicts: set[str] = field(default_factory=set)


class LiveBarBatcher:
    def __init__(self, symbols: Sequence[str], *, interval: str = "1m",
                 settings: LivePaperSettings | None = None, monotonic: Callable[[], float]) -> None:
        self.symbols = symbols_for_replay(symbols)
        next_open_time(datetime(2000, 1, 1, tzinfo=timezone.utc), interval)
        self.interval = interval
        self.settings = LivePaperSettings.model_validate(settings) if settings is not None else LivePaperSettings()
        self._monotonic = monotonic
        self._last_tick: float | None = None
        self._pending: dict[datetime, _Pending] = {}
        self._sealed: OrderedDict[datetime, dict[str, str]] = OrderedDict()
        self.watermark: datetime | None = None

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def retained_fingerprint_count(self) -> int:
        return sum(len(items) for items in self._sealed.values())

    def _tick(self) -> float:
        value = self._monotonic()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("monotonic clock must be finite")
        if self._last_tick is not None and value < self._last_tick:
            raise ValueError("monotonic clock moved backwards")
        self._last_tick = value
        return value

    def push(self, event: KlineEvent, *, now: datetime) -> BatchResult:
        if not aware(now):
            raise ValueError("batch clock must be an aware datetime")
        tick = self._tick()
        batches = self._flush(tick)

        def result(reason: str | None = None, boundary: datetime | None = None) -> BatchResult:
            notices = (BatchNotice(reason, getattr(event, "symbol", None), boundary),) if reason else ()
            return BatchResult(tuple(batches), notices)

        if not isinstance(event, KlineEvent):
            return result("not_a_candle")
        try:
            event = KlineEvent.model_validate(event)
            if event.symbol not in self.symbols or event.interval != self.interval:
                return result("bar_scope_mismatch")
            if not event.is_closed:
                return result("unfinished_candle")
            canonical = canonical_bar(event)
            end = canonical.close_time
            if not end <= event.event_time <= event.received_at <= now:
                return result("invalid_bar_clock", end)
        except (TypeError, ValueError, OverflowError):
            return result("invalid_finalized_bar")
        fingerprint = identity("live_bar", canonical)
        if self.watermark is not None and end <= self.watermark:
            previous = self._sealed.get(end, {}).get(event.symbol)
            reason = "duplicate_bar" if previous == fingerprint else "conflicting_late_bar" if previous else "late_bar"
            return result(reason, end)
        group = self._pending.get(end)
        if group is None:
            if len(self._pending) >= self.settings.pending_batch_limit:
                return result("batch_buffer_full", end)
            group = _Pending(tick + self.settings.batch_timeout_ms / 1000)
            self._pending[end] = group
        if event.symbol in group.conflicts:
            return result("conflicting_bar", end)
        previous = group.fingerprints.get(event.symbol)
        if previous is not None:
            if previous == fingerprint:
                return result("duplicate_bar", end)
            group.conflicts.add(event.symbol)
            group.bars.pop(event.symbol, None)
            group.fingerprints.pop(event.symbol, None)
            batches.extend(self._flush(tick))
            return result("conflicting_bar", end)
        group.bars[event.symbol] = event
        group.fingerprints[event.symbol] = fingerprint
        batches.extend(self._flush(tick))
        return result()

    def poll(self) -> BatchResult:
        return BatchResult(tuple(self._flush(self._tick())))

    def _flush(self, tick: float) -> list[LiveBarBatch]:
        output = []
        while self._pending:
            end = min(self._pending)
            group = self._pending[end]
            complete = len(group.bars) + len(group.conflicts) == len(self.symbols)
            if not complete and tick < group.deadline:
                break
            del self._pending[end]
            missing = tuple(symbol for symbol in self.symbols if symbol not in group.bars)
            output.append(LiveBarBatch(boundary=end, bars=tuple(group.bars[s] for s in sorted(group.bars)),
                missing_symbols=missing, conflicting_symbols=tuple(sorted(group.conflicts)),
                reason="conflict" if group.conflicts else "timeout" if missing else "complete"))
            self.watermark = end
            self._sealed[end] = group.fingerprints
            while len(self._sealed) > self.settings.pending_batch_limit:
                self._sealed.popitem(last=False)
        return output

    def discard_pending(self) -> None:
        """Loss/reconnect seals pending windows; they can never be replayed later."""
        if self._pending:
            latest = max(self._pending)
            self.watermark = max(self.watermark, latest) if self.watermark is not None else latest
        self._pending.clear()
