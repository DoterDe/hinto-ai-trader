"""Immutable virtual-capital research artifacts, independent of execution contracts."""

from decimal import Context, Decimal, localcontext
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from src.domain.backtesting import BacktestRunMetadata, Count, Directional, HistoricalInterval, PositiveCount
from src.domain.decisions import DecisionRecord
from src.domain.market_data import MarketSymbol, NonnegativeDecimal, PositiveDecimal
from src.domain.models import DomainModel, Identifier


class PortfolioModel(DomainModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioAction(str, Enum):
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
    RESERVED = "RESERVED"


class PortfolioReason(str, Enum):
    CAPACITY_RESERVED = "capacity_reserved"
    DECISION_NOT_ELIGIBLE = "decision_not_eligible"
    DUPLICATE_DECISION = "duplicate_decision"
    INVALID_STATE = "invalid_or_stale_portfolio_state"
    NONPOSITIVE_EQUITY = "nonpositive_equity"
    DRAWDOWN_LIMIT = "portfolio_drawdown_limit"
    SYMBOL_ACTIVE = "symbol_position_active"
    MAX_POSITIONS = "max_open_positions"
    GROSS_LIMIT = "gross_exposure_limit"
    SYMBOL_LIMIT = "symbol_exposure_limit"


class PaperExposure(PortfolioModel):
    symbol: MarketSymbol
    open_notional: NonnegativeDecimal = Decimal(0)
    reserved_notional: NonnegativeDecimal = Decimal(0)
    open_count: Count = 0
    reservation_count: Count = 0

    @model_validator(mode="after")
    def coherent_counts(self) -> Self:
        if (self.open_count == 0) != (self.open_notional == 0):
            raise ValueError("open count and notional must agree")
        if (self.reservation_count == 0) != (self.reserved_notional == 0):
            raise ValueError("reservation count and notional must agree")
        return self


class PaperPortfolioState(PortfolioModel):
    timestamp: AwareDatetime
    realized_equity: Decimal
    unrealized_net_pnl: Decimal | None
    marked_equity: Decimal | None
    peak_equity: PositiveDecimal
    drawdown: NonnegativeDecimal | None
    exposures: tuple[PaperExposure, ...] = ()
    open_notional: NonnegativeDecimal = Decimal(0)
    reserved_notional: NonnegativeDecimal = Decimal(0)
    gross_exposure: NonnegativeDecimal = Decimal(0)
    gross_exposure_fraction: NonnegativeDecimal | None = Decimal(0)
    open_count: Count = 0
    reservation_count: Count = 0

    @model_validator(mode="after")
    def reconciled_state(self) -> Self:
        with localcontext(Context(prec=34)):
            if tuple(item.symbol for item in self.exposures) != tuple(sorted({item.symbol for item in self.exposures})):
                raise ValueError("exposures must have unique sorted symbols")
            if (self.open_notional != sum((item.open_notional for item in self.exposures), Decimal(0))
                    or self.reserved_notional != sum((item.reserved_notional for item in self.exposures), Decimal(0))
                    or self.gross_exposure != self.open_notional + self.reserved_notional
                    or self.open_count != sum(item.open_count for item in self.exposures)
                    or self.reservation_count != sum(item.reservation_count for item in self.exposures)):
                raise ValueError("exposures must reconcile")
            if self.unrealized_net_pnl is None:
                if self.marked_equity is not None or self.drawdown is not None or self.gross_exposure_fraction is not None:
                    raise ValueError("unknown marks cannot produce equity or ratios")
            else:
                if self.marked_equity != self.realized_equity + self.unrealized_net_pnl:
                    raise ValueError("marked equity must reconcile")
                if self.peak_equity < self.marked_equity:
                    raise ValueError("peak cannot be below known equity")
                if self.drawdown != (self.peak_equity - self.marked_equity) / self.peak_equity:
                    raise ValueError("drawdown must reconcile")
                expected = self.gross_exposure / self.marked_equity if self.marked_equity > 0 else None
                if self.gross_exposure_fraction != expected:
                    raise ValueError("exposure fraction must reconcile")
        return self


class PortfolioDecisionRecord(PortfolioModel):
    portfolio_decision_id: Identifier
    upstream: DecisionRecord
    policy_id: Identifier
    state_id: Identifier
    evaluated_at: AwareDatetime
    action: PortfolioAction
    reason: PortfolioReason
    desired_notional: PositiveDecimal | None = None
    reservation_id: Identifier | None = None

    @model_validator(mode="after")
    def coherent_action(self) -> Self:
        reserved = self.action == PortfolioAction.RESERVED
        if reserved != (self.reason == PortfolioReason.CAPACITY_RESERVED):
            raise ValueError("reservation requires successful capacity reason")
        if reserved != (self.reservation_id is not None):
            raise ValueError("only reserved decisions carry a reservation ID")
        if reserved and (self.desired_notional is None or self.upstream.outcome != "ELIGIBLE"):
            raise ValueError("reservation requires eligible notional")
        return self


class PaperEntryReservation(PortfolioModel):
    reservation_id: Identifier
    decision_id: Identifier
    symbol: MarketSymbol
    direction: Directional
    virtual_notional: PositiveDecimal
    decision_time: AwareDatetime
    expected_entry_time: AwareDatetime
    policy_id: Identifier

    @model_validator(mode="after")
    def next_open_boundary(self) -> Self:
        if self.expected_entry_time != self.decision_time:
            raise ValueError("exclusive source close equals expected next open boundary")
        return self


class PaperReservationExpiry(PortfolioModel):
    reservation_id: Identifier
    observed_at: AwareDatetime
    reason: Literal["missing_entry_bar", "dataset_ended"]


class PaperPosition(PortfolioModel):
    position_id: Identifier
    reservation: PaperEntryReservation
    interval: HistoricalInterval
    entry_time: AwareDatetime
    entry_price_raw: PositiveDecimal
    holding_period_bars: PositiveCount
    bars_held: Count
    expected_next_open: AwareDatetime
    backtest_settings_id: Identifier
    status: Literal["OPEN", "CLOSED", "INCOMPLETE"] = "OPEN"
    reason: Literal["holding", "horizon_completed", "missing_horizon_bar", "dataset_ended"] = "holding"
    last_mark_time: AwareDatetime | None = None
    last_mark_price: PositiveDecimal | None = None

    @model_validator(mode="after")
    def coherent_position(self) -> Self:
        if self.entry_time != self.reservation.expected_entry_time or self.expected_next_open < self.entry_time:
            raise ValueError("position times must follow reservation")
        if self.bars_held > self.holding_period_bars:
            raise ValueError("position cannot exceed fixed horizon")
        if (self.last_mark_time is None) != (self.last_mark_price is None):
            raise ValueError("mark time and price must appear together")
        if self.last_mark_time is not None and not self.entry_time < self.last_mark_time <= self.expected_next_open:
            raise ValueError("mark must describe an observed holding bar")
        if self.status == "CLOSED":
            if self.reason != "horizon_completed" or self.bars_held != self.holding_period_bars:
                raise ValueError("closed position requires full horizon")
        elif self.status == "OPEN":
            if self.reason != "holding" or self.bars_held >= self.holding_period_bars:
                raise ValueError("open position must still be holding")
        elif self.reason not in ("missing_horizon_bar", "dataset_ended"):
            raise ValueError("incomplete position requires explicit reason")
        return self


class PaperPnl(PortfolioModel):
    gross_pnl: Decimal
    fee_cost: NonnegativeDecimal
    slippage_cost: NonnegativeDecimal
    total_cost: NonnegativeDecimal
    net_pnl: Decimal

    @model_validator(mode="after")
    def reconciled_pnl(self) -> Self:
        # Multiplying independently rounded Phase 6 returns by notional can
        # differ in the last few digits. Preserve N*net_return, not a new formula.
        with localcontext(Context(prec=34)):
            scale = max(abs(self.gross_pnl), abs(self.net_pnl), self.total_cost, self.fee_cost, self.slippage_cost)
            tolerance = scale * Decimal('1e-32')
            if (abs(self.total_cost-self.fee_cost-self.slippage_cost) > tolerance
                    or abs(self.net_pnl-(self.gross_pnl-self.total_cost)) > tolerance):
                raise ValueError("portfolio PnL components must reconcile within Decimal rounding")
        return self


class PaperPositionClose(PortfolioModel):
    close_id: Identifier
    position_id: Identifier
    exit_time: AwareDatetime
    exit_price_raw: PositiveDecimal
    pnl: PaperPnl


class PaperPortfolioCurvePoint(PortfolioModel):
    state: PaperPortfolioState
    cumulative_closed_pnl: PaperPnl
    open_count_before_exits: Count


class PaperSymbolMetrics(PortfolioModel):
    symbol: MarketSymbol
    opened_count: Count
    completed_count: Count
    incomplete_count: Count
    closed_pnl: PaperPnl


class PortfolioRejectionCount(PortfolioModel):
    reason: PortfolioReason
    count: PositiveCount


class PaperPortfolioMetrics(PortfolioModel):
    input_bar_count: Count
    evaluated_decision_count: Count
    upstream_eligible_count: Count
    upstream_blocked_count: Count
    upstream_no_action_count: Count
    reserved_count: Count
    rejected_count: Count
    ignored_count: Count
    opened_count: Count
    completed_count: Count
    incomplete_count: Count
    missing_entry_reservation_count: Count
    long_opened_count: Count
    short_opened_count: Count
    initial_virtual_equity: PositiveDecimal
    final_realized_equity: Decimal
    final_marked_equity: Decimal | None
    total_closed_pnl: PaperPnl
    outstanding_entry_fee_cost: NonnegativeDecimal
    outstanding_entry_slippage_cost: NonnegativeDecimal
    realized_total_return: Decimal
    peak_equity: PositiveDecimal
    max_drawdown: NonnegativeDecimal
    max_gross_exposure: NonnegativeDecimal
    max_observed_gross_exposure_fraction: NonnegativeDecimal
    max_simultaneous_open_positions: Count
    average_open_count: NonnegativeDecimal
    turnover: NonnegativeDecimal
    win_count: Count
    loss_count: Count
    flat_count: Count
    win_rate: Annotated[Decimal, Field(ge=0, le=1)] | None
    valuation_complete: Annotated[bool, Field(strict=True)]
    nonpositive_equity_observed: Annotated[bool, Field(strict=True)]
    per_symbol: tuple[PaperSymbolMetrics, ...]
    rejection_counts: tuple[PortfolioRejectionCount, ...]

    @model_validator(mode="after")
    def coherent_counts(self) -> Self:
        if (self.evaluated_decision_count != self.upstream_eligible_count + self.upstream_blocked_count + self.upstream_no_action_count
                or self.upstream_eligible_count != self.reserved_count + self.rejected_count
                or self.ignored_count != self.upstream_blocked_count + self.upstream_no_action_count
                or self.reserved_count != self.opened_count + self.missing_entry_reservation_count
                or self.opened_count != self.completed_count + self.incomplete_count
                or self.opened_count != self.long_opened_count + self.short_opened_count
                or self.completed_count != self.win_count + self.loss_count + self.flat_count
                or self.rejected_count != sum(item.count for item in self.rejection_counts)):
            raise ValueError("portfolio counts must reconcile")
        return self


class PaperPortfolioRunMetadata(BacktestRunMetadata):
    portfolio_policy_id: Identifier
    status: Literal["COMPLETE", "INCOMPLETE"]


class PaperPortfolioReport(PortfolioModel):
    metadata: PaperPortfolioRunMetadata
    decisions: tuple[PortfolioDecisionRecord, ...]
    reservations: tuple[PaperEntryReservation, ...]
    expiries: tuple[PaperReservationExpiry, ...]
    positions: tuple[PaperPosition, ...]
    closes: tuple[PaperPositionClose, ...]
    curve: tuple[PaperPortfolioCurvePoint, ...]
    final_state: PaperPortfolioState | None
    metrics: PaperPortfolioMetrics
    limitations: tuple[str, ...]
