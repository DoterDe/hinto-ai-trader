"""Closed-price return and Wilder RSI primitives with explicit missing values."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from src.indicators._numeric import positive, safe_decimal, valid_period


@safe_decimal
def simple_return(current: Decimal, previous: Decimal) -> Decimal | None:
    """Fractional close-to-close return, using strictly positive prices."""
    if not positive((current, previous)):
        return None
    return (current - previous) / previous


@safe_decimal
def log_return(current: Decimal, previous: Decimal) -> float | None:
    """Natural log price ratio, exposed as a finite float for statistics."""
    if not positive((current, previous)):
        return None
    value = float((current / previous).ln())
    return value if math.isfinite(value) else None


@safe_decimal
def rolling_return(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """N-change fractional return; N+1 positive closes are required."""
    if not valid_period(period) or len(closes) <= period or not positive(closes):
        return None
    return (closes[-1] - closes[-period - 1]) / closes[-period - 1]


@safe_decimal
def roc(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """N-change rate of change in percent, not a fractional return."""
    value = rolling_return(closes, period)
    return None if value is None else value * 100


@safe_decimal
def momentum(closes: Sequence[Decimal]) -> Decimal | None:
    """Latest close minus previous close, in price units."""
    if len(closes) < 2 or not positive(closes):
        return None
    return closes[-1] - closes[-2]


@safe_decimal
def rsi(closes: Sequence[Decimal], period: int) -> Decimal | None:
    """Wilder RSI seeded by N changes, then smoothed with alpha=1/N.

    A gain-only window is 100, a loss-only window is 0, and a flat window is 50.
    N+1 closes are needed to establish the seed. Retained bounded history defines
    the seed, so results do not depend on discarded observations.
    """
    if not valid_period(period) or len(closes) <= period or not positive(closes):
        return None
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gain = sum((max(change, Decimal(0)) for change in changes[:period]), Decimal(0)) / period
    loss = sum((max(-change, Decimal(0)) for change in changes[:period]), Decimal(0)) / period
    for change in changes[period:]:
        gain = (gain * (period - 1) + max(change, Decimal(0))) / period
        loss = (loss * (period - 1) + max(-change, Decimal(0))) / period
    if loss == 0:
        return Decimal(50) if gain == 0 else Decimal(100)
    if gain == 0:
        return Decimal(0)
    return Decimal(100) - Decimal(100) / (Decimal(1) + gain / loss)
