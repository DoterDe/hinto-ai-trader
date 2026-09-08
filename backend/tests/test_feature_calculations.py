from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
from typing import Any

import pytest
from pydantic import ValidationError

from src.application.feature_calculations import calculate_group
from src.application.feature_settings import FeatureSettings
from src.domain.features import (
    MarkFundingFeatures, MicrostructureFeatures, MomentumFeatures, RegimeFeatures,
    ReturnFeatures, TradeFeatures, TrendFeatures, VolatilityFeatures, VolumeFeatures,
)
from src.domain.market_data import BookTickerEvent, KlineEvent, MarkPriceEvent, TradeEvent


D = Decimal
START = datetime(2026, 9, 8, tzinfo=timezone.utc)
NOW = START + timedelta(hours=1)
SETTINGS = FeatureSettings(
    ema_fast=1, ema_slow=2, ema_long=3, rsi_period=2, atr_period=2,
    roc_period=2, volatility_window=2, relative_volume_window=2,
    vwap_window=2, rolling_return_windows=(1, 2), history_limit=10,
)


def candle(index: int, close: str, volume: str = "2", taker: str = "1") -> KlineEvent:
    start = START + timedelta(minutes=index)
    end = start + timedelta(minutes=1) - timedelta(milliseconds=1)
    price, base, buy = D(close), D(volume), D(taker)
    return KlineEvent(
        symbol="BTCUSDT", event_time=end, received_at=end, interval="1m",
        open_time=start, close_time=end, open=price, high=price + 2, low=price - 2,
        close=price, volume=base, quote_volume=price * base, trade_count=10,
        is_closed=True, taker_buy_volume=buy, taker_buy_quote_volume=price * buy,
    )


def bars() -> tuple[KlineEvent, ...]:
    return (candle(0, "10", "1"), candle(1, "20", "2"),
            candle(2, "30", "3"), candle(3, "40", "6", "4"))


def trade() -> TradeEvent:
    return TradeEvent(
        symbol="BTCUSDT", event_time=NOW, received_at=NOW,
        aggregate_trade_id=1, first_trade_id=1, last_trade_id=2,
        price="40.125", quantity="0.005", trade_time=NOW, buyer_is_maker=False,
    )


def book() -> BookTickerEvent:
    return BookTickerEvent(
        symbol="BTCUSDT", event_time=NOW, received_at=NOW, update_id=1,
        bid_price="99", ask_price="101", bid_quantity="3", ask_quantity="1",
        transaction_time=NOW,
    )


def mark() -> MarkPriceEvent:
    return MarkPriceEvent(
        symbol="BTCUSDT", event_time=NOW, received_at=NOW, mark_price="102",
        index_price="100", funding_rate="-0.0001",
        next_funding_time=NOW + timedelta(hours=8),
    )


def test_trade_values_keep_decimal_precision_without_history() -> None:
    result = calculate_group("trade", (), SETTINGS, event=trade(), now=NOW)
    assert isinstance(result, TradeFeatures)
    assert result.price == D("40.125")
    assert result.quantity == D("0.005")


def test_return_values_have_explicit_window_and_units() -> None:
    result = calculate_group("returns", bars(), SETTINGS, now=NOW)
    assert isinstance(result, ReturnFeatures)
    assert result.close == D("40")
    assert result.simple_return == D("0.3333333333333333333333333333333333")
    assert result.log_return == pytest.approx(0.2876820724517809)
    assert tuple(value.window for value in result.rolling_returns) == (1, 2)
    assert result.rolling_returns[0].value == D("0.3333333333333333333333333333333333")
    assert result.rolling_returns[1].value == D("1")


def test_trend_values_use_fractional_distances_and_signed_spreads() -> None:
    result = calculate_group("trend", bars(), SETTINGS, now=NOW)
    assert isinstance(result, TrendFeatures)
    assert (result.ema_fast, result.ema_slow, result.ema_long) == (D("40"), D("35"), D("30"))
    assert result.fast_slow_spread == result.slow_long_spread == D("5")
    assert result.distance_from_fast == D("0")
    assert result.distance_from_slow == D("0.1428571428571428571428571428571429")
    assert result.distance_from_long == D("0.3333333333333333333333333333333333")


def test_momentum_values_keep_rsi_roc_and_price_change_units() -> None:
    result = calculate_group("momentum", bars(), SETTINGS, now=NOW)
    assert isinstance(result, MomentumFeatures)
    assert result.rsi == D("100")
    assert result.roc_percent == D("100")
    assert result.close_change == D("10")


def test_volatility_values_have_known_tr_atr_and_sample_log_variance() -> None:
    history = (candle(0, "100"), candle(1, "200"), candle(2, "800"))
    result = calculate_group("volatility", history, SETTINGS, now=NOW)
    assert isinstance(result, VolatilityFeatures)
    # True ranges 4, 102, 602: two-range seed 53, next Wilder value 327.5.
    assert result.true_range == D("602")
    assert result.atr == D("327.5")
    assert result.normalized_atr == D("0.409375")
    assert result.atr_percent == D("40.9375")
    assert result.realized_volatility == pytest.approx(0.49012907173427356)


def test_volume_values_use_closed_candle_reported_volumes() -> None:
    result = calculate_group("volume", bars(), SETTINGS, now=NOW)
    assert isinstance(result, VolumeFeatures)
    assert result.rolling_vwap == D("36.66666666666666666666666666666667")
    assert result.relative_volume == D("2.4")
    assert result.taker_buy_ratio == D("0.6666666666666666666666666666666667")
    assert result.taker_base_volume_delta_proxy == D("2")


def test_microstructure_values_need_no_candle_history() -> None:
    result = calculate_group("microstructure", (), SETTINGS, event=book(), now=NOW)
    assert result == MicrostructureFeatures(
        bid="99", ask="101", midpoint="100", spread="2", spread_bps="200",
        bid_quantity="3", ask_quantity="1", top_of_book_imbalance="0.5",
    )


@pytest.mark.parametrize("seconds", [28800, 0, -1, -60.5])
def test_mark_funding_values_preserve_signed_time_until_funding(seconds: float) -> None:
    event = mark().model_copy(update={"next_funding_time": NOW + timedelta(seconds=seconds)})
    result = calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW)
    assert isinstance(result, MarkFundingFeatures)
    assert result.mark_price == D("102")
    assert result.index_price == D("100")
    assert result.basis == D("2")
    assert result.basis_percent == D("2")
    assert result.basis_bps == D("200")
    assert result.funding_rate == D("-0.0001")
    assert result.seconds_until_funding == seconds


def test_regime_values_are_numeric_context_only() -> None:
    result = calculate_group("regime", bars(), SETTINGS, now=NOW)
    assert isinstance(result, RegimeFeatures)
    assert result.normalized_atr == D("0.275")
    assert result.normalized_ema_separation == D("0.1428571428571428571428571428571429")
    assert result.directional_efficiency == D("1")
    assert result.relative_volume == D("2.4")


@pytest.mark.parametrize("name", ["returns", "trend", "momentum", "volatility", "volume", "regime"])
def test_candle_groups_require_complete_warmup(name: str) -> None:
    assert calculate_group(name, (), SETTINGS, now=NOW) is None
    assert calculate_group(name, bars()[:1], SETTINGS, now=NOW) is None


@pytest.mark.parametrize("name", ["returns", "trend", "momentum", "volatility", "volume", "regime"])
def test_candle_groups_reject_open_or_future_history(name: str) -> None:
    history = bars()
    assert calculate_group(name, history[:-1] + (history[-1].model_copy(update={"is_closed": False}),),
                           SETTINGS, now=NOW) is None
    assert calculate_group(name, history, SETTINGS, now=START) is None


@pytest.mark.parametrize("name", ["trade", "microstructure", "mark_funding"])
def test_observation_groups_require_correct_event_type(name: str) -> None:
    assert calculate_group(name, bars(), SETTINGS, now=NOW) is None
    assert calculate_group(name, bars(), SETTINGS, event=bars()[-1], now=NOW) is None


def test_zero_denominators_make_whole_group_unavailable() -> None:
    empty_book = book().model_copy(update={"bid_quantity": D("0"), "ask_quantity": D("0")})
    assert calculate_group("microstructure", (), SETTINGS, event=empty_book, now=NOW) is None
    zero_volume = candle(3, "40", "0", "0")
    assert calculate_group("volume", bars()[:-1] + (zero_volume,), SETTINGS, now=NOW) is None
    flat = tuple(candle(i, "10") for i in range(4))
    assert calculate_group("regime", flat, SETTINGS, now=NOW) is None
    # A flat RSI is explicitly defined; it does not share efficiency's denominator.
    result = calculate_group("momentum", flat, SETTINGS, now=NOW)
    assert isinstance(result, MomentumFeatures)
    assert result.rsi == D("50")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "0", "-1"])
def test_invalid_trade_or_mark_prices_never_become_values(value: str) -> None:
    bad_trade = trade().model_copy(update={"price": D(value)})
    bad_mark = mark().model_copy(update={"mark_price": D(value)})
    assert calculate_group("trade", (), SETTINGS, event=bad_trade, now=NOW) is None
    assert calculate_group("mark_funding", (), SETTINGS, event=bad_mark, now=NOW) is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_funding_rate_is_rejected_by_output_model(value: str) -> None:
    event = mark().model_copy(update={"funding_rate": D(value)})
    assert calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW) is None


def test_extreme_finite_arithmetic_overflow_remains_unavailable() -> None:
    event = mark().model_copy(update={"mark_price": D("1e1000000")})
    assert calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW) is None
    event = book().model_copy(update={"bid_price": D("1e1000000"), "ask_price": D("2e1000000")})
    assert calculate_group("microstructure", (), SETTINGS, event=event, now=NOW) is None


def test_unknown_group_and_naive_timestamp_are_unavailable() -> None:
    assert calculate_group("unknown", bars(), SETTINGS, now=NOW) is None
    assert calculate_group("trade", (), SETTINGS, event=trade(), now=NOW.replace(tzinfo=None)) is None
    event = mark().model_copy(update={"next_funding_time": NOW.replace(tzinfo=None)})
    assert calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW) is None


def test_outputs_are_immutable_and_finite_in_json() -> None:
    history = bars()
    for name, event in [("trade", trade()), ("microstructure", book()), ("mark_funding", mark()),
                        ("returns", None), ("trend", None), ("momentum", None),
                        ("volatility", None), ("volume", None), ("regime", None)]:
        result = calculate_group(name, history, SETTINGS, event=event, now=NOW)
        assert result is not None
        encoded = result.model_dump_json()
        assert "NaN" not in encoded and "Infinity" not in encoded
        json.loads(encoded, parse_constant=lambda value: pytest.fail(f"Nonfinite JSON: {value}"))
        key = next(iter(type(result).model_fields))
        with pytest.raises(ValidationError, match="frozen"):
            setattr(result, key, None)


def test_outer_calculations_ignore_callers_decimal_context() -> None:
    history = bars()
    event = mark()
    expected_regime = calculate_group("regime", history, SETTINGS, now=NOW)
    expected_mark = calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW)
    with localcontext() as context:
        context.prec = 2
        assert calculate_group("regime", history, SETTINGS, now=NOW) == expected_regime
        assert calculate_group("mark_funding", (), SETTINGS, event=event, now=NOW) == expected_mark
