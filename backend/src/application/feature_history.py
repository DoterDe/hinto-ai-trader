"""Bounded closed candles with explicit continuity loss, without synthetic bars."""

import re
from collections import deque
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter, ValidationError

from src.domain.market_data import KlineEvent, MarketSymbol, NormalizedMarketEvent


def next_open_time(open_time: datetime, interval: str) -> datetime:
    """Advance a normalized interval in UTC; calendar months aren't fixed days."""
    if open_time.tzinfo is None or open_time.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    match = re.fullmatch(r"([1-9][0-9]*)([smhdwM])", interval)
    if match is None:
        raise ValueError("invalid candle interval")
    count, unit = int(match[1]), match[2]
    start = open_time.astimezone(timezone.utc)
    try:
        if unit == "M":
            if start.day != 1 or any((start.hour, start.minute, start.second, start.microsecond)):
                raise ValueError("calendar month candles must start at UTC month boundaries")
            month_index = start.year * 12 + start.month - 1 + count
            return start.replace(year=month_index // 12, month=month_index % 12 + 1)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return start + timedelta(seconds=count * seconds)
    except (OverflowError, ValueError) as error:
        raise ValueError("invalid or overflowing candle interval") from error


class FeatureHistory:
    def __init__(self, symbol: str, interval: str, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("history limit must be a positive integer")
        next_open_time(datetime(2000, 1, 1, tzinfo=timezone.utc), interval)
        self.symbol = TypeAdapter(MarketSymbol).validate_python(symbol.upper())
        self.interval = interval
        self.limit = limit
        self._closed: deque[KlineEvent] = deque(maxlen=limit)
        self._last: KlineEvent | None = None
        self.resets = 0
        self.last_reset: str | None = None

    @property
    def closed(self) -> tuple[KlineEvent, ...]:
        return tuple(self._closed)

    def reset(self, reason: str) -> None:
        self._closed.clear()
        self._last = None
        self.resets += 1
        self.last_reset = reason

    def accept(self, event: NormalizedMarketEvent, *, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not isinstance(event, KlineEvent) or event.symbol != self.symbol or event.interval != self.interval:
            return False
        try:
            event = KlineEvent.model_validate(event)
        except ValidationError:
            self.reset("invalid_candle")
            return False
        try:
            end = next_open_time(event.open_time, self.interval)
        except ValueError:
            self.reset("invalid_candle")
            return False
        if (event.event_time > now or event.received_at > now
                or event.open_time > event.event_time
                or (event.is_closed and (end > event.event_time or end > now or event.close_time > event.event_time))):
            return False  # An impossible clock must not advance ordering.
        previous = self._last
        if previous is not None:
            if event.open_time < previous.open_time or event.event_time < previous.event_time:
                return False
            if previous.open_time < event.open_time < next_open_time(previous.open_time, self.interval):
                self.reset("overlapping_candle")
                return False
            if event.open_time == previous.open_time:
                if previous.is_closed:
                    if event.is_closed and self._final_values(event) != self._final_values(previous):
                        self.reset("closed_candle_revision")
                        self._last = event  # Seal the disputed window; recover on a later bar.
                    return False
                if event.trade_count < previous.trade_count:
                    return False
                if event.event_time == previous.event_time and event.trade_count == previous.trade_count and not event.is_closed:
                    return False
        if (event.close_time > end or event.close_time <= event.open_time
                or event.low > min(event.open, event.close) or event.high < max(event.open, event.close)
                or event.low > event.high or event.taker_buy_volume > event.volume
                or event.taker_buy_quote_volume > event.quote_volume):
            self.reset("invalid_candle")
            return False
        missed_open_close = previous is not None and not previous.is_closed and event.open_time > previous.open_time
        missed_closed_successor = bool(self._closed) and event.open_time > next_open_time(self._closed[-1].open_time, self.interval)
        if missed_open_close or missed_closed_successor:
            self.reset("candle_gap")
        self._last = event
        if not event.is_closed:
            return False
        self._closed.append(event)
        return True

    @staticmethod
    def _final_values(event: KlineEvent) -> tuple[object, ...]:
        return (event.close_time, event.open, event.high, event.low, event.close,
                event.volume, event.quote_volume, event.trade_count,
                event.taker_buy_volume, event.taker_buy_quote_volume)
