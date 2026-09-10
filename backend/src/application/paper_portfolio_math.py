"""Pure marked-equity and virtual-notional calculations in the Phase 6 context."""

from datetime import datetime
from decimal import Decimal

from pydantic import TypeAdapter

from src.application.backtest_math import arithmetic, outcome_returns
from src.application.backtest_settings import BacktestSettings
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.backtesting import Directional
from src.domain.market_data import PositiveDecimal
from src.domain.paper_portfolio import PaperExposure, PaperPnl, PaperPortfolioState, PortfolioReason


@arithmetic
def desired_notional(equity: Decimal, settings: PaperPortfolioSettings) -> Decimal:
    equity = TypeAdapter(PositiveDecimal).validate_python(equity)
    settings = PaperPortfolioSettings.model_validate(settings)
    return TypeAdapter(PositiveDecimal).validate_python(equity * settings.target_position_fraction)


@arithmetic
def portfolio_state(*, timestamp: datetime, realized: Decimal, unrealized: Decimal | None,
                    peak: Decimal, exposures: tuple[PaperExposure, ...] = ()) -> PaperPortfolioState:
    realized = TypeAdapter(Decimal).validate_python(realized)
    if not realized.is_finite():
        raise ValueError("realized equity must be finite")
    peak = TypeAdapter(PositiveDecimal).validate_python(peak)
    if unrealized is not None:
        unrealized = TypeAdapter(Decimal).validate_python(unrealized)
        if not unrealized.is_finite():
            raise ValueError("unrealized value must be finite")
    exposures = tuple(sorted((PaperExposure.model_validate(item) for item in exposures), key=lambda item: item.symbol))
    marked = realized + unrealized if unrealized is not None else None
    peak = max(peak, marked) if marked is not None else peak
    opened = sum((item.open_notional for item in exposures), Decimal(0))
    reserved = sum((item.reserved_notional for item in exposures), Decimal(0))
    gross = opened + reserved
    return PaperPortfolioState(timestamp=timestamp, realized_equity=realized, unrealized_net_pnl=unrealized,
        marked_equity=marked, peak_equity=peak, drawdown=(peak-marked)/peak if marked is not None else None,
        exposures=exposures, open_notional=opened, reserved_notional=reserved, gross_exposure=gross,
        gross_exposure_fraction=gross/marked if marked is not None and marked > 0 else None,
        open_count=sum(item.open_count for item in exposures), reservation_count=sum(item.reservation_count for item in exposures))


@arithmetic
def capacity_reason(state: PaperPortfolioState, symbol: str, notional: Decimal,
                    settings: PaperPortfolioSettings) -> PortfolioReason | None:
    state, settings = PaperPortfolioState.model_validate(state), PaperPortfolioSettings.model_validate(settings)
    notional = TypeAdapter(PositiveDecimal).validate_python(notional)
    if state.marked_equity is None:
        return PortfolioReason.INVALID_STATE
    if state.marked_equity <= 0:
        return PortfolioReason.NONPOSITIVE_EQUITY
    if state.drawdown >= settings.max_drawdown_fraction:
        return PortfolioReason.DRAWDOWN_LIMIT
    exposure = next((item for item in state.exposures if item.symbol == symbol), PaperExposure(symbol=symbol))
    if exposure.open_count + exposure.reservation_count:
        return PortfolioReason.SYMBOL_ACTIVE
    if state.open_count + state.reservation_count >= settings.max_open_positions:
        return PortfolioReason.MAX_POSITIONS
    if state.gross_exposure + notional > state.marked_equity * settings.max_gross_exposure_fraction:
        return PortfolioReason.GROSS_LIMIT
    if exposure.open_notional + exposure.reserved_notional + notional > state.marked_equity * settings.max_symbol_exposure_fraction:
        return PortfolioReason.SYMBOL_LIMIT
    return None


@arithmetic
def marked_pnl(notional: Decimal, entry: Decimal, current: Decimal, direction: str,
               settings: BacktestSettings) -> PaperPnl:
    """Gross directional mark minus entry-side slippage/fee only; no exit cost."""
    notional, entry, current = (TypeAdapter(PositiveDecimal).validate_python(item) for item in (notional, entry, current))
    direction = TypeAdapter(Directional).validate_python(direction)
    settings = BacktestSettings.model_validate(settings)
    sign = Decimal(1) if direction == "LONG" else Decimal(-1)
    slip, fee = settings.slippage_bps_per_side / 10000, settings.fee_bps_per_side / 10000
    gross = notional * (sign * (current-entry) / entry)
    slip_cost, fee_cost = notional * slip, notional * fee * (1 + sign*slip)
    cost = slip_cost + fee_cost
    return PaperPnl(gross_pnl=gross, fee_cost=fee_cost, slippage_cost=slip_cost, total_cost=cost, net_pnl=gross-cost)


@arithmetic
def closed_pnl(notional: Decimal, entry: Decimal, exit: Decimal, direction: str,
               settings: BacktestSettings) -> PaperPnl:
    notional = TypeAdapter(PositiveDecimal).validate_python(notional)
    returns = outcome_returns(entry, exit, direction, settings)
    return PaperPnl(gross_pnl=notional*returns.gross_return, fee_cost=notional*returns.fee_cost_return,
        slippage_cost=notional*returns.slippage_cost_return, total_cost=notional*returns.simulated_cost_return,
        net_pnl=notional*returns.net_return)
