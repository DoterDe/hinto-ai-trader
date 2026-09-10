"""Strict final-bar contract over existing KlineEvent, with streaming ordering."""

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timedelta, timezone

from pydantic import TypeAdapter

from src.application.feature_history import next_open_time
from src.domain.market_data import KlineEvent, MarketSymbol


def symbols_for_replay(symbols: Sequence[str]) -> tuple[str, ...]:
    if isinstance(symbols, str) or not symbols:
        raise ValueError("replay requires configured symbols")
    values = tuple(TypeAdapter(MarketSymbol).validate_python(symbol) for symbol in symbols)
    if len(set(values)) != len(values):
        raise ValueError("replay symbols must be unique")
    return tuple(sorted(values))


def validate_bar(event: KlineEvent) -> KlineEvent:
    """A final OHLCV bar is available at its exclusive UTC interval end.

    Input close_time may use the exclusive end or end-minus-1ms convention;
    normalize both to the exclusive boundary. Publication/receipt are exactly
    that boundary. This is a bar-availability assumption, not exchange latency.
    """
    if not isinstance(event, KlineEvent):
        raise TypeError("historical input must be a KlineEvent")
    for name in ("open_time", "close_time", "event_time", "received_at"):
        value = getattr(event, name, None)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("historical timestamps must be aware datetimes")
    event = KlineEvent.model_validate(event)
    opened = event.open_time.astimezone(timezone.utc)
    end = next_open_time(opened, event.interval)
    count, unit = int(event.interval[:-1]), event.interval[-1]
    if unit == "M":
        aligned = ((opened.year - 1970) * 12 + opened.month - 1) % count == 0
    else:
        anchor = datetime(1970, 1, 5 if unit == "w" else 1, tzinfo=timezone.utc)
        width = end - opened
        aligned = (opened - anchor) % width == timedelta(0)
    if not aligned:
        raise ValueError("historical interval is not aligned to its UTC grid")
    if (not event.is_closed or event.event_time != end or event.received_at != end
            or event.close_time not in (end, end - timedelta(milliseconds=1))):
        raise ValueError("historical bar must be finalized and available at interval end")
    if not event.low <= min(event.open, event.close) <= max(event.open, event.close) <= event.high:
        raise ValueError("historical OHLC is inconsistent")
    if (event.taker_buy_volume > event.volume or event.taker_buy_quote_volume > event.quote_volume
            or (event.volume == 0 and event.quote_volume != 0)):
        raise ValueError("historical volume is inconsistent")
    return KlineEvent.model_validate(event.model_copy(update={
        "open_time": opened, "close_time": end, "event_time": end, "received_at": end}))


def ordered_bars(bars: Iterable[KlineEvent], *, symbols: Sequence[str], interval: str) -> Iterator[KlineEvent]:
    """Input times must increase; equal-time symbol groups are sorted in O(S) space.

    Gaps are preserved. Duplicates/older/overlapping/mixed-interval bars fail the
    run. One next-time item can be read ahead, never published into the pipeline.
    """
    allowed = symbols_for_replay(symbols)
    next_open_time(datetime(2000, 1, 1, tzinfo=timezone.utc), interval)
    group: dict[str, KlineEvent] = {}
    timestamp: datetime | None = None
    for raw in bars:
        event = validate_bar(raw)
        if event.symbol not in allowed or event.interval != interval:
            raise ValueError("historical symbol or interval differs from replay scope")
        if timestamp is not None and event.event_time < timestamp:
            raise ValueError("historical times must be nondecreasing")
        if timestamp is not None and event.event_time != timestamp:
            yield from (group[symbol] for symbol in sorted(group))
            group.clear()
        timestamp = event.event_time
        if event.symbol in group:
            raise ValueError("duplicate historical bar")
        group[event.symbol] = event
    yield from (group[symbol] for symbol in sorted(group))
