"""Pure numerical trend context; no trading labels or decisions.

EMA uses an initial period-length simple average, followed by alpha=2/(N+1).
The result is seeded from the supplied bounded history on each calculation.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from src.indicators._numeric import positive, safe_decimal, valid_period


@safe_decimal
def ema(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """SMA-seeded EMA; requires N positive, finite closed-candle prices."""
    if not valid_period(period) or len(closes) < period or not positive(closes):
        return None
    value = sum(closes[:period], Decimal(0)) / period
    alpha = Decimal(2) / (period + 1)
    for close in closes[period:]:
        value += alpha * (close - value)
    return value


@safe_decimal
def ema_spread(fast: Decimal | None, slow: Decimal | None) -> Decimal | None:
    """Signed price-unit difference between two available EMAs."""
    if not positive((fast, slow)):
        return None
    return fast - slow


@safe_decimal
def price_distance(price: Decimal | None, average: Decimal | None) -> Decimal | None:
    """Signed fractional distance (price - average) / average."""
    if not positive((price, average)):
        return None
    return (price - average) / average


@safe_decimal
def directional_efficiency(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """Absolute N-change displacement / path length; flat paths are undefined."""
    if not valid_period(period) or len(closes) <= period or not positive(closes):
        return None
    window = closes[-period - 1:]
    path = sum((abs(current - previous)
                for previous, current in zip(window, window[1:])), Decimal(0))
    if path == 0:
        return None
    return abs(window[-1] - window[0]) / path
