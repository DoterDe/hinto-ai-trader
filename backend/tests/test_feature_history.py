from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.application.feature_history import FeatureHistory, next_open_time
from src.domain.market_data import KlineEvent, TradeEvent


START = datetime(2026, 9, 8, tzinfo=timezone.utc)


def candle(minute: int = 0, **updates: Any) -> KlineEvent:
    opened = START + timedelta(minutes=minute)
    observed = opened + timedelta(minutes=1)
    return KlineEvent(**(dict(
        symbol="BTCUSDT", event_time=observed, received_at=observed,
        interval="1m", open_time=opened, close_time=observed - timedelta(milliseconds=1),
        open="10", high="12", low="9", close="11", volume="2", quote_volume="22",
        trade_count=4, is_closed=True, taker_buy_volume="1", taker_buy_quote_volume="11",
    ) | updates))


def history(limit: int = 5) -> FeatureHistory:
    return FeatureHistory("BTCUSDT", "1m", limit)


def accept(value: FeatureHistory, event: KlineEvent) -> bool:
    return value.accept(event, now=event.received_at)


def test_empty_history_and_first_closed_candle() -> None:
    value = history()
    assert value.closed == ()
    assert value.resets == 0
    assert value.last_reset is None
    first = candle()
    assert accept(value, first)
    assert value.closed == (first,)


def test_open_updates_do_not_enter_closed_history() -> None:
    value = history()
    opened = candle(is_closed=False, event_time=START + timedelta(seconds=20),
                    received_at=START + timedelta(seconds=20), close="10")
    progressed = candle(is_closed=False, event_time=START + timedelta(seconds=40),
                        received_at=START + timedelta(seconds=40))
    assert not accept(value, opened)
    assert not accept(value, progressed)
    assert value.closed == ()
    assert accept(value, candle())
    assert len(value.closed) == 1
    assert value.resets == 0


def test_duplicates_are_ignored_but_closed_revisions_invalidate_history() -> None:
    value = history()
    first = candle()
    assert accept(value, first)
    assert not accept(value, first)
    assert value.closed == (first,)
    assert value.resets == 0
    revised = candle(close="12", trade_count=5,
                     event_time=first.event_time + timedelta(seconds=1),
                     received_at=first.received_at + timedelta(seconds=1))
    assert not accept(value, revised)
    assert value.closed == ()
    assert value.last_reset == "closed_candle_revision"
    assert not accept(value, revised)
    assert accept(value, candle(1))
    assert value.closed == (candle(1),)
    assert value.resets == 1


def test_out_of_order_candles_do_not_rewrite_or_reset_history() -> None:
    value = history()
    first, second = candle(1), candle(2)
    assert accept(value, first)
    assert accept(value, second)
    assert not value.accept(candle(0), now=second.received_at)
    assert not value.accept(candle(1, close="12"), now=second.received_at)
    assert value.closed == (first, second)
    assert value.resets == 0


def test_older_event_timestamp_does_not_advance_open_window_watermark() -> None:
    value = history()
    first = candle()
    assert accept(value, first)
    stale_open = candle(1, is_closed=False,
                        event_time=START + timedelta(seconds=50),
                        received_at=START + timedelta(seconds=70))
    assert not accept(value, stale_open)
    assert accept(value, candle(1))
    assert value.closed == (first, candle(1))


def test_bounded_history_evicts_only_oldest_closed_observation() -> None:
    value = history(limit=3)
    events = tuple(candle(index) for index in range(7))
    for index, event in enumerate(events):
        assert accept(value, event)
        assert len(value.closed) <= 3
        assert value.closed == events[max(0, index - 2):index + 1]
    assert value.resets == 0
    old_snapshot = value.closed
    assert accept(value, candle(7))
    assert old_snapshot == events[-3:]


def test_limit_one_retains_only_latest_observation() -> None:
    value = history(limit=1)
    assert accept(value, candle())
    assert accept(value, candle(1))
    assert value.closed == (candle(1),)


def test_skipped_closed_window_resets_continuity_and_rebuilds() -> None:
    value = history()
    assert accept(value, candle())
    assert accept(value, candle(2))
    assert value.closed == (candle(2),)
    assert value.resets == 1
    assert value.last_reset == "candle_gap"
    assert accept(value, candle(3))
    assert value.closed == (candle(2), candle(3))
    assert value.resets == 1


def test_moving_past_an_observed_unclosed_candle_resets_history() -> None:
    value = history()
    assert accept(value, candle())
    assert not accept(value, candle(1, is_closed=False))
    assert not accept(value, candle(2, is_closed=False))
    assert value.closed == ()
    assert value.last_reset == "candle_gap"
    assert value.resets == 1
    assert accept(value, candle(2))
    assert value.closed == (candle(2),)


def test_consecutive_open_and_closed_windows_do_not_create_false_gap() -> None:
    value = history()
    for minute in range(4):
        observed = START + timedelta(minutes=minute, seconds=30)
        assert not accept(value, candle(minute, is_closed=False,
                                       event_time=observed, received_at=observed))
        assert accept(value, candle(minute))
    assert len(value.closed) == 4
    assert value.resets == 0


def test_different_symbol_or_interval_cannot_mutate_history() -> None:
    value = history()
    assert accept(value, candle())
    assert not accept(value, candle(2, symbol="ETHUSDT"))
    assert not accept(value, candle(2, interval="5m"))
    assert value.closed == (candle(),)
    assert value.resets == 0


def test_other_normalized_event_types_are_ignored() -> None:
    value = history()
    event = TradeEvent(symbol="BTCUSDT", event_time=START, received_at=START,
                       aggregate_trade_id=1, first_trade_id=1, last_trade_id=1,
                       price="10", quantity="1", trade_time=START, buyer_is_maker=False)
    assert not value.accept(event, now=START)
    assert value.closed == ()
    assert value.resets == 0


def test_symbols_are_normalized() -> None:
    value = FeatureHistory("btcusdt", "1m", 5)
    assert accept(value, candle())
    assert value.closed == (candle(),)


@pytest.mark.parametrize("field", ["event_time", "received_at", "close_time"])
def test_future_observation_does_not_poison_acceptable_history(field: str) -> None:
    value = history()
    first = candle()
    assert accept(value, first)
    coherent = candle(1)
    future = coherent.model_copy(update={field: coherent.received_at + timedelta(seconds=1)})
    assert not value.accept(future, now=coherent.received_at)
    assert value.closed == (first,)
    assert accept(value, coherent)
    assert value.closed == (first, coherent)
    assert value.resets == 0


def test_future_open_update_does_not_skip_current_window() -> None:
    value = history()
    assert accept(value, candle())
    future = candle(10, is_closed=False)
    assert not value.accept(future, now=candle(1).received_at)
    assert accept(value, candle(1))
    assert value.closed == (candle(), candle(1))
    assert value.resets == 0


@pytest.mark.parametrize("update", [
    {"high": "9"}, {"low": "12"}, {"open": "13"}, {"close": "8"},
    {"taker_buy_volume": "3"}, {"taker_buy_quote_volume": "23"},
])
def test_invalid_candle_resets_history_and_allows_corrected_unsealed_window(
    update: dict[str, str],
) -> None:
    value = history()
    assert accept(value, candle())
    assert not accept(value, candle(1, **update))
    assert value.closed == ()
    assert value.last_reset == "invalid_candle"
    assert value.resets == 1
    assert accept(value, candle(1))
    assert value.closed == (candle(1),)


@pytest.mark.parametrize("update", [
    {"close": Decimal("NaN")}, {"volume": Decimal(-1)},
    {"event_time": START.replace(tzinfo=None)}, {"is_closed": "true"},
])
def test_model_copies_are_revalidated(update: dict[str, Any]) -> None:
    value = history()
    assert accept(value, candle())
    malformed = candle(1).model_copy(update=update)
    assert not value.accept(malformed, now=candle(1).received_at)
    assert value.closed == ()
    assert value.last_reset == "invalid_candle"
    assert accept(value, candle(1))


def test_closed_candle_must_end_inside_its_interval() -> None:
    value = history()
    assert accept(value, candle())
    invalid = candle(1, close_time=START + timedelta(minutes=2, seconds=1),
                     event_time=START + timedelta(minutes=2, seconds=2),
                     received_at=START + timedelta(minutes=2, seconds=2))
    assert not accept(value, invalid)
    assert value.closed == ()
    assert value.last_reset == "invalid_candle"


def test_closed_candle_end_resolution_is_not_exchange_specific() -> None:
    value = history()
    event = candle(close_time=START + timedelta(seconds=59))
    assert accept(value, event)
    assert accept(value, candle(1))
    assert value.resets == 0


def test_exclusive_end_timestamp_is_also_supported() -> None:
    assert accept(history(), candle(close_time=START + timedelta(minutes=1)))


def test_closed_flag_before_expected_interval_end_does_not_create_lookahead() -> None:
    value = history()
    early = candle(close_time=START + timedelta(seconds=20),
                   event_time=START + timedelta(seconds=30), received_at=START + timedelta(seconds=30))
    assert not accept(value, early)
    assert value.closed == ()
    assert accept(value, candle())


def test_independent_symbol_histories_do_not_share_resets_or_evictions() -> None:
    btc, eth = history(limit=1), FeatureHistory("ETHUSDT", "1m", 2)
    assert accept(btc, candle())
    assert accept(eth, candle(symbol="ETHUSDT"))
    assert accept(btc, candle(2))
    assert btc.resets == 1
    assert eth.resets == 0
    assert len(eth.closed) == 1


def test_monthly_boundary_uses_utc_even_with_offset_input() -> None:
    opened = datetime(2024, 2, 1, 5, tzinfo=timezone(timedelta(hours=5)))
    assert next_open_time(opened, "1M") == datetime(2024, 3, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("closed", [False, True])
def test_overlapping_candle_windows_invalidate_continuity(closed: bool) -> None:
    value = history()
    assert accept(value, candle())
    overlapping = candle(open_time=START + timedelta(seconds=30),
                         close_time=START + timedelta(seconds=89),
                         event_time=START + timedelta(seconds=90),
                         received_at=START + timedelta(seconds=90), is_closed=closed)
    assert not accept(value, overlapping)
    assert value.closed == ()
    assert value.last_reset == "overlapping_candle"
    assert accept(value, candle(1))


def test_overlap_after_closed_revision_is_not_a_valid_recovery() -> None:
    value = history()
    assert accept(value, candle())
    assert not accept(value, candle(close="12", event_time=START + timedelta(seconds=61),
                                   received_at=START + timedelta(seconds=61)))
    assert value.closed == ()
    overlap = candle(open_time=START + timedelta(seconds=30),
                     close_time=START + timedelta(seconds=89),
                     event_time=START + timedelta(seconds=90), received_at=START + timedelta(seconds=90))
    assert not accept(value, overlap)
    assert value.last_reset == "overlapping_candle"


def test_explicit_reset_clears_ordering_as_well_as_history() -> None:
    value = history()
    assert accept(value, candle(3))
    value.reset("subscriber_gap")
    assert value.closed == ()
    assert value.last_reset == "subscriber_gap"
    assert value.resets == 1
    assert accept(value, candle())
    assert value.closed == (candle(),)


def test_naive_evaluation_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        history().accept(candle(), now=START.replace(tzinfo=None))


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.0, "2", None])
def test_history_limit_requires_positive_strict_integer(limit: Any) -> None:
    with pytest.raises(ValueError):
        FeatureHistory("BTCUSDT", "1m", limit)


@pytest.mark.parametrize("symbol", ["", "BTC/USDT", "BTC USDT", "A"])
def test_invalid_history_symbols_are_rejected(symbol: str) -> None:
    with pytest.raises(ValueError):
        FeatureHistory(symbol, "1m", 5)


@pytest.mark.parametrize("interval", ["", "0m", "-1m", "1y", "1.5m", "1m trailing", "m"])
def test_invalid_intervals_are_rejected(interval: str) -> None:
    with pytest.raises(ValueError):
        next_open_time(START, interval)
    with pytest.raises(ValueError):
        FeatureHistory("BTCUSDT", interval, 5)


@pytest.mark.parametrize("interval,expected", [
    ("1s", START + timedelta(seconds=1)), ("15m", START + timedelta(minutes=15)),
    ("2h", START + timedelta(hours=2)), ("3d", START + timedelta(days=3)),
    ("2w", START + timedelta(days=14)),
])
def test_fixed_interval_boundaries(interval: str, expected: datetime) -> None:
    assert next_open_time(START, interval) == expected


@pytest.mark.parametrize("opened,interval,expected", [
    (datetime(2024, 2, 1, tzinfo=timezone.utc), "1M", datetime(2024, 3, 1, tzinfo=timezone.utc)),
    (datetime(2023, 2, 1, tzinfo=timezone.utc), "1M", datetime(2023, 3, 1, tzinfo=timezone.utc)),
    (datetime(2026, 12, 1, tzinfo=timezone.utc), "1M", datetime(2027, 1, 1, tzinfo=timezone.utc)),
    (datetime(2026, 11, 1, tzinfo=timezone.utc), "3M", datetime(2027, 2, 1, tzinfo=timezone.utc)),
])
def test_month_intervals_use_calendar_boundaries(
    opened: datetime, interval: str, expected: datetime,
) -> None:
    assert next_open_time(opened, interval) == expected


def test_monthly_history_is_contiguous_across_leap_february() -> None:
    value = FeatureHistory("BTCUSDT", "1M", 5)
    months = [(datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 2, 1, tzinfo=timezone.utc)),
              (datetime(2024, 2, 1, tzinfo=timezone.utc), datetime(2024, 3, 1, tzinfo=timezone.utc))]
    for opened, following in months:
        event = candle(interval="1M", open_time=opened,
                       close_time=following - timedelta(milliseconds=1),
                       event_time=following, received_at=following)
        assert accept(value, event)
    assert len(value.closed) == 2
    assert value.resets == 0


@pytest.mark.parametrize("opened", [
    datetime(2026, 9, 2, tzinfo=timezone.utc), datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
    datetime(2026, 9, 1, 0, 0, 1, tzinfo=timezone.utc),
])
def test_monthly_boundaries_require_first_day_at_utc_midnight(opened: datetime) -> None:
    with pytest.raises(ValueError):
        next_open_time(opened, "1M")


def test_naive_and_impossible_interval_boundaries_are_rejected() -> None:
    with pytest.raises(ValueError):
        next_open_time(START.replace(tzinfo=None), "1m")
    with pytest.raises(ValueError):
        next_open_time(datetime(9999, 12, 1, tzinfo=timezone.utc), "1M")
    with pytest.raises(ValueError):
        next_open_time(START, "9999999999999999999999999999999d")
