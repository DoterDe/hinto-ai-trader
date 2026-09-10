"""Independent virtual-state examples; no network or wall clock."""

from decimal import Decimal

from backtest_fixtures import START, bar, historical_decision
from src.application.paper_portfolio_math import portfolio_state


def state(equity="100000", *, peak="100000", unrealized="0", exposures=(), timestamp=START):
    return portfolio_state(timestamp=timestamp, realized=Decimal(equity),
        unrealized=Decimal(unrealized) if unrealized is not None else None,
        peak=Decimal(peak), exposures=exposures)


def decision(index=0, *, symbol="BTCUSDT", direction="LONG", outcome="ELIGIBLE", **updates):
    original = historical_decision(bar(index, symbol=symbol), direction=direction, outcome=outcome).decision
    return type(original).model_validate(original.model_copy(update=updates))
