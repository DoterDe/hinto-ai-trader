"""Costs and directional returns normalized to the raw next-open entry price."""

from collections.abc import Callable
from decimal import Context, Decimal, DecimalException, Underflow, localcontext
from functools import wraps
from typing import ParamSpec, TypeVar

from pydantic import TypeAdapter

from src.application.backtest_settings import BacktestSettings
from src.domain.backtesting import Directional, OutcomeReturns
from src.domain.market_data import PositiveDecimal
from src.domain.strategies import StrategyDirection

P = ParamSpec("P")
T = TypeVar("T")


def arithmetic(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            with localcontext(Context(prec=34)) as context:
                context.traps[Underflow] = True
                return function(*args, **kwargs)
        except (DecimalException, OverflowError, ZeroDivisionError) as error:
            raise ValueError("invalid backtest arithmetic") from error
    return guarded


@arithmetic
def outcome_returns(entry: Decimal, exit: Decimal, direction: StrategyDirection,
                    settings: BacktestSettings) -> OutcomeReturns:
    """For sign d, E'=E(1+d*s), X'=X(1-d*s); all returns divide by raw E.

    Gross=d*(X-E)/E; slippage=s*(1+X/E); fee=f*(E'+X')/E.
    Costs are nonnegative for either direction. There is no position quantity.
    """
    entry, exit = (TypeAdapter(PositiveDecimal).validate_python(value) for value in (entry, exit))
    direction = TypeAdapter(Directional).validate_python(direction)
    settings = BacktestSettings.model_validate(settings)
    sign = Decimal(1) if direction == StrategyDirection.LONG else Decimal(-1)
    slip, fee = settings.slippage_bps_per_side / 10000, settings.fee_bps_per_side / 10000
    effective_entry = entry * (1 + sign * slip)
    effective_exit = exit * (1 - sign * slip)
    gross = sign * (exit - entry) / entry
    slippage_cost = slip * (1 + exit / entry)
    fee_cost = fee * (effective_entry + effective_exit) / entry
    total = slippage_cost + fee_cost
    return OutcomeReturns(effective_entry_price=effective_entry, effective_exit_price=effective_exit,
        gross_return=gross, slippage_cost_return=slippage_cost, fee_cost_return=fee_cost,
        simulated_cost_return=total, net_return=gross - total)
