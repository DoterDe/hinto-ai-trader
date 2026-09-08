from decimal import Decimal, localcontext
from typing import Any

import pytest

from src.indicators.momentum import log_return, momentum, roc, rolling_return, rsi, simple_return
from src.indicators.trend import directional_efficiency, ema, ema_spread, price_distance


def prices(*values: str | int) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def test_ema_known_sequence_and_sma_seed() -> None:
    assert ema(prices(10, 11, 9), 3) == Decimal(10)
    assert ema(prices(10, 11, 9, 12), 3) == Decimal(11)
    assert ema(prices(10, 11, 9, 12, 8), 3) == Decimal("9.5")
    assert ema(prices(1, 2, 3, 4, 5), 3) == Decimal(4)


def test_ema_period_one_is_latest_price() -> None:
    assert ema(prices(10, 6, 13), 1) == Decimal(13)


def test_trend_spreads_and_price_distance_are_signed() -> None:
    assert ema_spread(Decimal(110), Decimal(100)) == Decimal(10)
    assert ema_spread(Decimal(100), Decimal(110)) == Decimal(-10)
    assert price_distance(Decimal(90), Decimal(100)) == Decimal("-0.1")
    assert price_distance(Decimal(110), Decimal(100)) == Decimal("0.1")


@pytest.mark.parametrize("invalid", [None, Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
def test_trend_pair_invalid_or_missing_values(invalid: Any) -> None:
    for function in (ema_spread, price_distance):
        assert function(invalid, Decimal(10)) is None
        assert function(Decimal(10), invalid) is None


def test_directional_efficiency_known_path_and_flat_case() -> None:
    # Net change 3 over a path of 2 + 1 + 2 = 5.
    assert directional_efficiency(prices(10, 12, 11, 13), 3) == Decimal("0.6")
    assert directional_efficiency(prices(10, 11, 12), 2) == Decimal(1)
    assert directional_efficiency(prices(12, 11, 10), 2) == Decimal(1)
    assert directional_efficiency(prices(10, 11, 10), 2) == Decimal(0)
    assert directional_efficiency(prices(10, 10, 10), 2) is None
    assert directional_efficiency(prices(10, 12, 11, 13), 1) == Decimal(1)


def test_returns_roc_and_price_momentum_use_distinct_units() -> None:
    sequence = prices(100, 110, 99, 120)
    assert simple_return(Decimal(110), Decimal(100)) == Decimal("0.1")
    assert simple_return(Decimal(99), Decimal(110)) == Decimal("-0.1")
    assert rolling_return(sequence, 3) == Decimal("0.2")
    assert roc(sequence, 3) == Decimal(20)
    assert momentum(sequence) == Decimal(21)
    assert rolling_return(prices(999, 100, 120), 1) == Decimal("0.2")
    assert momentum(prices(100, 90)) == Decimal(-10)


def test_log_return_known_constants_and_flat_price() -> None:
    assert log_return(Decimal(2), Decimal(1)) == pytest.approx(0.6931471805599453)
    assert log_return(Decimal(1), Decimal(2)) == pytest.approx(-0.6931471805599453)
    assert log_return(Decimal(100), Decimal(100)) == 0.0


@pytest.mark.parametrize("function", [simple_return, log_return])
@pytest.mark.parametrize("invalid", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"), True, 1.0, None])
def test_pair_returns_reject_invalid_prices(function: Any, invalid: Any) -> None:
    assert function(invalid, Decimal(10)) is None
    assert function(Decimal(10), invalid) is None


def test_rsi_known_wilder_seed_and_recursive_step() -> None:
    # Seed gains 2, 0, 3 and losses 0, 1, 0 give RSI 250/3.
    assert rsi(prices(10, 12, 11, 14), 3) == pytest.approx(
        Decimal("83.33333333333333333333333333333333"), abs=Decimal("1e-30")
    )
    # The next loss of 2 yields smoothed gains 10/9 and losses 8/9.
    assert rsi(prices(10, 12, 11, 14, 12), 3) == pytest.approx(
        Decimal("55.55555555555555555555555555555556"), abs=Decimal("1e-30")
    )


@pytest.mark.parametrize(
    "values,expected",
    [((1, 2, 3, 4, 5), 100), ((5, 4, 3, 2, 1), 0), ((4, 4, 4, 4, 4), 50)],
)
def test_rsi_gain_loss_and_flat_cases(values: tuple[int, ...], expected: int) -> None:
    assert rsi(prices(*values), 3) == Decimal(expected)


def test_rsi_period_one_handles_current_change_including_flat() -> None:
    assert rsi(prices(5, 4, 6), 1) == Decimal(100)
    assert rsi(prices(5, 6, 4), 1) == Decimal(0)
    assert rsi(prices(5, 6, 6), 1) == Decimal(50)


@pytest.mark.parametrize("function", [ema, rsi, roc, rolling_return, directional_efficiency])
@pytest.mark.parametrize("period", [0, -1, True, False, 2.0, "2", None])
def test_periods_are_positive_strict_integers(function: Any, period: Any) -> None:
    assert function(prices(10, 11, 12), period) is None


@pytest.mark.parametrize("function", [ema, rsi, roc, rolling_return, directional_efficiency])
@pytest.mark.parametrize("values", [(), (10,), (10, 11)])
def test_insufficient_history(function: Any, values: tuple[int, ...]) -> None:
    assert function(prices(*values), 3) is None


def test_change_indicators_require_one_more_close_than_period() -> None:
    assert ema(prices(1, 2, 3), 3) == Decimal(2)
    for function in (rsi, roc, rolling_return, directional_efficiency):
        assert function(prices(1, 2, 3), 3) is None
    assert momentum(()) is None
    assert momentum(prices(10)) is None


@pytest.mark.parametrize("invalid", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), None, True])
def test_history_functions_reject_invalid_prices(invalid: Any) -> None:
    sequence = [Decimal(10), invalid, Decimal(12), Decimal(11)]
    for function in (ema, rsi, roc, rolling_return, directional_efficiency):
        assert function(sequence, 2) is None
    assert momentum(sequence) is None


def test_extreme_arithmetic_is_unavailable_instead_of_infinite() -> None:
    assert simple_return(Decimal("1e999999"), Decimal("1e-999999")) is None
    assert rolling_return(prices("1e-999999", "1e999999"), 1) is None
    assert roc(prices("1e-999999", "1e999999"), 1) is None
    assert log_return(Decimal("1e999999"), Decimal("1e-999999")) is None
    assert ema(prices("9e999999", "9e999999"), 2) is None


def test_calculations_ignore_ambient_decimal_precision() -> None:
    sequence = prices("10.1234567890123456789", "12.1", "11.4", "14.2", "12.2")
    with localcontext() as context:
        context.prec = 34
        expected = (ema(sequence, 3), rsi(sequence, 3), rolling_return(sequence, 3),
                    log_return(sequence[-1], sequence[-2]), directional_efficiency(sequence, 3))
    with localcontext() as context:
        context.prec = 4
        assert (ema(sequence, 3), rsi(sequence, 3), rolling_return(sequence, 3),
                log_return(sequence[-1], sequence[-2]), directional_efficiency(sequence, 3)) == expected
