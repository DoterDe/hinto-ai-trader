from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import Any

import pytest

from src.domain.market_data import KlineEvent
from src.indicators.microstructure import (
    basis, basis_bps, imbalance, midpoint, spread, spread_bps,
)
from src.indicators.volatility import atr, realized_volatility, true_range
from src.indicators.volume import (
    relative_volume, rolling_vwap, taker_buy_ratio, taker_volume_delta_proxy,
)


D = Decimal
START = datetime(2026, 9, 8, tzinfo=timezone.utc)


def candle(index: int = 0, **changes: Any) -> KlineEvent:
    start = START + timedelta(minutes=index)
    end = start + timedelta(minutes=1) - timedelta(milliseconds=1)
    values: dict[str, Any] = dict(
        symbol="BTCUSDT", event_time=end, received_at=end, interval="1m",
        open_time=start, close_time=end, open="10", high="12", low="8",
        close="10", volume="10", quote_volume="100", trade_count=10,
        is_closed=True, taker_buy_volume="6", taker_buy_quote_volume="60",
    )
    return KlineEvent(**(values | changes))


@pytest.mark.parametrize(
    "high,low,previous,expected",
    [("12", "8", None, "4"), ("12", "8", "10", "4"),
     ("12", "8", "15", "7"), ("12", "8", "5", "7"),
     ("10", "10", "10", "0")],
)
def test_true_range_includes_gaps(
    high: str, low: str, previous: str | None, expected: str,
) -> None:
    assert true_range(D(high), D(low), D(previous) if previous else None) == D(expected)


@pytest.mark.parametrize(
    "high,low,previous",
    [("8", "12", "10"), ("0", "0", None), ("12", "8", "0"),
     ("NaN", "8", "10"), ("12", "Infinity", "10"),
     ("12", "8", "-Infinity")],
)
def test_true_range_invalid_input_is_unavailable(
    high: str, low: str, previous: str | None,
) -> None:
    assert true_range(D(high), D(low), D(previous) if previous else None) is None


def test_wilder_atr_known_ohlc_sequence_and_seed() -> None:
    bars = [
        candle(0, open="9", high="10", low="8", close="9"),
        candle(1, open="10", high="12", low="9", close="11"),
        candle(2, open="11", high="14", low="10", close="12"),
        candle(3, open="12", high="15", low="11", close="14"),
        candle(4, open="14", high="15", low="12", close="13"),
    ]
    # TRs: 2, 3, 4, 4, 3; seed=3, next=10/3, final=29/9.
    assert atr(bars[:2], 3) is None
    assert atr(bars[:3], 3) == D("3")
    assert abs(atr(bars, 3) - D("3.222222222222222222222222222222222")) < D("1e-30")
    assert atr(bars, 1) == D("3")


@pytest.mark.parametrize(
    "changes",
    [{"is_closed": False}, {"high": D("9")}, {"low": D("11")},
     {"open": D("13")}, {"close": D("7")}, {"high": D("Infinity")},
     {"close": D("NaN")}, {"low": D("-1")}],
)
def test_atr_rejects_invalid_or_open_candles(changes: dict[str, Any]) -> None:
    assert atr([candle().model_copy(update=changes)], 1) is None


@pytest.mark.parametrize("period", [0, -1, True, 1.5, "2"])
def test_invalid_periods_are_unavailable(period: Any) -> None:
    bars = [candle(), candle(1), candle(2)]
    assert atr(bars, period) is None
    assert rolling_vwap(bars, period) is None
    assert relative_volume(bars, period) is None
    assert realized_volatility([D("1"), D("2"), D("3")], period) is None


def test_empty_windows_and_insufficient_history() -> None:
    assert atr([], 1) is None
    assert rolling_vwap([], 1) is None
    assert relative_volume([], 1) is None
    assert rolling_vwap([candle()], 2) is None
    assert relative_volume([candle()], 1) is None
    assert realized_volatility([], 2) is None
    assert realized_volatility([D("1"), D("2")], 2) is None
    assert realized_volatility([D("1"), D("2")], 1) is None


def test_realized_volatility_known_sample_standard_deviation() -> None:
    # Last two log returns are ln(2) and ln(4), yielding ln(2)/sqrt(2).
    assert realized_volatility([D("100"), D("200"), D("800")], 2) == pytest.approx(
        0.49012907173427356, abs=1e-15,
    )
    assert realized_volatility([D("10")] * 4, 3) == 0.0
    assert realized_volatility([D("1"), D("2"), D("4"), D("8")], 3) == pytest.approx(
        0.0, abs=1e-30,
    )


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_realized_volatility_rejects_nonpositive_nonfinite_prices(bad: str) -> None:
    assert realized_volatility([D("1"), D(bad), D("2")], 2) is None


@pytest.mark.parametrize("scale", ["1e10000", "1e-10000"])
def test_realized_volatility_avoids_float_price_conversion(scale: str) -> None:
    closes = [D(scale), D(scale) * 2, D(scale) * 8]
    assert realized_volatility(closes, 2) == pytest.approx(0.49012907173427356)


def test_volume_known_values_use_reported_base_and_quote_volumes() -> None:
    bars = [
        candle(0, volume="2", quote_volume="20", taker_buy_volume="1",
               taker_buy_quote_volume="10"),
        candle(1, volume="4", quote_volume="44", taker_buy_volume="2",
               taker_buy_quote_volume="22"),
        candle(2, volume="9", quote_volume="108", taker_buy_volume="6",
               taker_buy_quote_volume="72"),
    ]
    assert rolling_vwap(bars[:2], 2) == D("10.66666666666666666666666666666667")
    assert rolling_vwap(bars, 1) == D("12")
    assert relative_volume(bars, 2) == D("3")
    assert taker_buy_ratio(bars[-1]) == D("0.6666666666666666666666666666666667")
    assert taker_volume_delta_proxy(bars[-1]) == D("3")


@pytest.mark.parametrize("taker,ratio,delta", [("0", "0", "-10"), ("5", "0.5", "0"),
                                            ("10", "1", "10")])
def test_taker_ratio_and_proxy_boundaries(taker: str, ratio: str, delta: str) -> None:
    bar = candle(taker_buy_volume=taker)
    assert taker_buy_ratio(bar) == D(ratio)
    assert taker_volume_delta_proxy(bar) == D(delta)


def test_zero_volume_denominators_remain_unavailable() -> None:
    zero = candle(volume="0", quote_volume="0", taker_buy_volume="0",
                  taker_buy_quote_volume="0")
    assert rolling_vwap([zero], 1) is None
    assert relative_volume([zero, candle(1)], 1) is None
    assert taker_buy_ratio(zero) is None
    assert taker_volume_delta_proxy(zero) == D("0")
    assert relative_volume([candle(), zero], 1) == D("0")


@pytest.mark.parametrize(
    "changes",
    [{"is_closed": False}, {"volume": D("-1")}, {"quote_volume": D("-1")},
     {"taker_buy_volume": D("-1")}, {"taker_buy_quote_volume": D("-1")},
     {"taker_buy_volume": D("11")}, {"taker_buy_quote_volume": D("101")},
     {"volume": D("NaN")}, {"quote_volume": D("Infinity")},
     {"taker_buy_volume": D("NaN")}, {"taker_buy_quote_volume": D("Infinity")},
     {"volume": D("0"), "taker_buy_volume": D("0")}],
)
def test_invalid_volume_data_is_not_used(changes: dict[str, Any]) -> None:
    invalid = candle().model_copy(update=changes)
    assert rolling_vwap([invalid], 1) is None
    assert relative_volume([invalid, candle(1)], 1) is None
    assert relative_volume([candle(), invalid], 1) is None
    assert taker_buy_ratio(invalid) is None
    assert taker_volume_delta_proxy(invalid) is None


def test_rolling_windows_ignore_older_values_outside_the_window() -> None:
    invalid = candle().model_copy(update={"volume": D("NaN")})
    assert rolling_vwap([invalid, candle()], 1) == D("10")
    assert relative_volume([invalid, candle(), candle(1)], 1) == D("1")
    assert realized_volatility([D("NaN"), D("100"), D("200"), D("800")], 2) == pytest.approx(
        0.49012907173427356,
    )


def test_book_prices_spread_and_top_imbalance() -> None:
    assert midpoint(D("99"), D("101")) == D("100")
    assert spread(D("99"), D("101")) == D("2")
    assert spread_bps(D("99"), D("101")) == D("200")
    assert imbalance(D("3"), D("1")) == D("0.5")
    assert imbalance(D("0"), D("2")) == D("-1")
    assert imbalance(D("2"), D("0")) == D("1")
    assert imbalance(D("0"), D("0")) is None
    assert spread(D("100"), D("100")) == 0
    assert spread_bps(D("100"), D("100")) == 0


@pytest.mark.parametrize(
    "bid,ask", [("101", "99"), ("0", "100"), ("99", "0"),
                ("-1", "100"), ("NaN", "100"), ("99", "Infinity")],
)
def test_invalid_or_crossed_book_prices_are_unavailable(bid: str, ask: str) -> None:
    assert midpoint(D(bid), D(ask)) is None
    assert spread(D(bid), D(ask)) is None
    assert spread_bps(D(bid), D(ask)) is None


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "-Infinity"])
def test_invalid_book_quantities_are_unavailable(value: str) -> None:
    assert imbalance(D(value), D("1")) is None
    assert imbalance(D("1"), D(value)) is None


def test_mark_index_basis_is_signed_and_uses_index_denominator() -> None:
    assert basis(D("102"), D("100")) == D("2")
    assert basis_bps(D("102"), D("100")) == D("200")
    assert basis(D("99"), D("100")) == D("-1")
    assert basis_bps(D("99"), D("100")) == D("-100")
    assert basis_bps(D("100"), D("100")) == D("0")


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_invalid_mark_index_prices_are_unavailable(value: str) -> None:
    assert basis(D(value), D("100")) is None
    assert basis(D("100"), D(value)) is None
    assert basis_bps(D(value), D("100")) is None
    assert basis_bps(D("100"), D(value)) is None


def test_fixed_decimal_precision_ignores_callers_context() -> None:
    with localcontext() as context:
        context.prec = 2
        assert midpoint(D("0.123456789012345678"), D("0.123456789012345680")) == D(
            "0.123456789012345679",
        )
        assert imbalance(D("2"), D("1")) == D("0.3333333333333333333333333333333333")
        assert rolling_vwap([candle(volume="6", taker_buy_volume="3")], 1) == D(
            "16.66666666666666666666666666666667",
        )


def test_decimal_arithmetic_overflow_is_unavailable() -> None:
    extreme = D("1e1000000")
    assert midpoint(extreme, extreme) is None
    assert spread(D("1"), extreme) is None
    assert basis(extreme, D("1")) is None
