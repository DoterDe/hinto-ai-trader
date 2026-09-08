"""A fixed arithmetic context independent of the caller's Decimal settings."""

from collections.abc import Callable, Iterable
from decimal import Context, Decimal, DecimalException, Underflow, localcontext
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def safe_decimal(function: Callable[P, T]) -> Callable[P, T | None]:
    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> T | None:
        try:
            with localcontext(Context(prec=34)) as context:
                context.traps[Underflow] = True
                result = function(*args, **kwargs)
                if isinstance(result, Decimal) and not result.is_finite():
                    return None
                return result
        except (DecimalException, ValueError, OverflowError, ZeroDivisionError):
            return None
    return guarded


def valid_period(period: int) -> bool:
    return type(period) is int and period > 0


def positive(values: Iterable[Decimal]) -> bool:
    return all(isinstance(value, Decimal) and value.is_finite() and value > 0 for value in values)


@safe_decimal
def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if not numerator.is_finite() or not denominator.is_finite() or denominator == 0:
        return None
    return numerator / denominator
