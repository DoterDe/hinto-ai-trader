"""Closed-candle volatility; realized volatility is not annualized."""

from collections.abc import Sequence
from decimal import Decimal
import math

from src.domain.market_data import KlineEvent
from src.indicators._numeric import positive, safe_decimal, valid_period


@safe_decimal
def true_range(
    high: Decimal, low: Decimal, previous_close: Decimal | None = None,
) -> Decimal | None:
    """Use high-low for the first observation; otherwise include price gaps."""
    if not positive((high, low)) or high < low:
        return None
    if previous_close is None:
        return high - low
    if not positive((previous_close,)):
        return None
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


@safe_decimal
def atr(candles: Sequence[KlineEvent], period: int) -> Decimal | None:
    """Wilder ATR seeded by the mean of N TRs, including first high-low.

    The retained closed history is the complete calculation input. Invalid
    OHLC or open candles make the result unavailable.
    """
    if not valid_period(period) or len(candles) < period:
        return None
    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        if (
            not candle.is_closed
            or not positive((candle.open, candle.high, candle.low, candle.close))
            or not candle.low <= min(candle.open, candle.close)
            or not max(candle.open, candle.close) <= candle.high
        ):
            return None
        current = true_range(candle.high, candle.low, previous_close)
        if current is None:
            return None
        ranges.append(current)
        previous_close = candle.close
    value = sum(ranges[:period], Decimal(0)) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


@safe_decimal
def realized_volatility(closes: Sequence[Decimal], window: int) -> float | None:
    """Sample standard deviation of the last N close-to-close log returns.

    Requires N >= 2 and N+1 closes. Decimal logarithms precede float conversion,
    avoiding overflow from converting large price levels or price ratios.
    """
    if not valid_period(window) or window < 2 or len(closes) < window + 1:
        return None
    selected = closes[-(window + 1):]
    if not positive(selected):
        return None
    returns = [float(current.ln() - previous.ln())
               for previous, current in zip(selected, selected[1:])]
    if not all(math.isfinite(value) for value in returns):
        return None
    mean = math.fsum(returns) / window
    variance = math.fsum((value - mean) ** 2 for value in returns) / (window - 1)
    value = math.sqrt(variance)
    return value if math.isfinite(value) else None
