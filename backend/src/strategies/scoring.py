"""Small piecewise scoring primitives with explicit invalid-input rejection."""

import math
from collections.abc import Callable
from decimal import Context, Decimal, DecimalException, Underflow, localcontext
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
Number = Decimal | int | float | str


def number(value: Number) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise ValueError("a finite numerical value is required")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("a finite numerical value is required")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (DecimalException, ValueError) as error:
        raise ValueError("a finite numerical value is required") from error
    if not result.is_finite():
        raise ValueError("a finite numerical value is required")
    return result


def arithmetic(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            with localcontext(Context(prec=34)) as context:
                context.traps[Underflow] = True
                return function(*args, **kwargs)
        except (DecimalException, OverflowError, ZeroDivisionError) as error:
            raise ValueError("invalid scoring arithmetic") from error
    return guarded


def clamp(value: Number, lower: Number = 0, upper: Number = 1) -> Decimal:
    value, lower, upper = number(value), number(lower), number(upper)
    if lower > upper:
        raise ValueError("clamp bounds are reversed")
    return min(upper, max(lower, value))


@arithmetic
def linear_quality(value: Number, zero_at: Number, one_at: Number) -> Decimal:
    """0 at/below zero_at, 1 at/above one_at, linear strictly between."""
    value, low, high = number(value), number(zero_at), number(one_at)
    if low >= high:
        raise ValueError("quality bounds must increase")
    if value <= low:
        return Decimal(0)
    if value >= high:
        return Decimal(1)
    return (value - low) / (high - low)


@arithmetic
def signed_score(value: Number, dead_zone: Number, saturation: Number) -> Decimal:
    """Signed [-1,1] ramp with an inclusive symmetric neutral dead zone."""
    value, dead, limit = number(value), number(dead_zone), number(saturation)
    if dead < 0 or limit <= dead:
        raise ValueError("require 0 <= dead_zone < saturation")
    magnitude = value.copy_abs()
    strength = linear_quality(magnitude, dead, limit)
    return strength if value >= 0 else -strength


@arithmetic
def dead_zone_score(value: Number, lower_limit: Number, neutral_low: Number,
                    neutral_high: Number, upper_limit: Number) -> Decimal:
    """Asymmetric signed ramp, useful for RSI thresholds in their native units."""
    value, floor, low, high, ceiling = map(number, (value, lower_limit, neutral_low, neutral_high, upper_limit))
    if not floor < low < high < ceiling:
        raise ValueError("dead-zone thresholds must strictly increase")
    if value < low:
        return -linear_quality(-value, -low, -floor)
    if value > high:
        return linear_quality(value, high, ceiling)
    return Decimal(0)


def sign(value: Number) -> Decimal:
    value = number(value)
    return Decimal(1) if value > 0 else Decimal(-1) if value < 0 else Decimal(0)
