"""Immutable offline signal-validation artifacts, without executable fields."""

from decimal import Context, Decimal, localcontext
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from src.domain.market_data import MarketSymbol, NonnegativeDecimal, PositiveDecimal
from src.domain.models import DomainModel, Identifier
from src.domain.strategies import StrategyDirection
from src.domain.decisions import DecisionRecord
from src.domain.features import RegimeFeatures

PositiveCount = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Directional = Literal[StrategyDirection.LONG, StrategyDirection.SHORT]
HistoricalInterval = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*[smhdwM]$")]


class BacktestModel(DomainModel):
    model_config = ConfigDict(extra="forbid")


class BacktestOutcomeStatus(str, Enum):
    COMPLETED = "COMPLETED"
    INCOMPLETE = "INCOMPLETE"


class OutcomeReason(str, Enum):
    HORIZON_COMPLETED = "horizon_completed"
    MISSING_ENTRY_BAR = "missing_entry_bar"
    MISSING_HORIZON_BAR = "missing_horizon_bar"
    DATASET_ENDED = "dataset_ended"


class OutcomeReturns(BacktestModel):
    effective_entry_price: PositiveDecimal
    effective_exit_price: PositiveDecimal
    gross_return: Decimal
    slippage_cost_return: NonnegativeDecimal
    fee_cost_return: NonnegativeDecimal
    simulated_cost_return: NonnegativeDecimal
    net_return: Decimal

    @model_validator(mode="after")
    def reconciled_returns(self) -> Self:
        with localcontext(Context(prec=34)):
            if self.simulated_cost_return != self.slippage_cost_return + self.fee_cost_return:
                raise ValueError("cost components must reconcile")
            if self.net_return != self.gross_return - self.simulated_cost_return:
                raise ValueError("gross, cost and net returns must reconcile")
        return self


class BacktestSignalOutcome(BacktestModel):
    outcome_id: Identifier
    decision_id: Identifier
    observation_id: Identifier
    symbol: MarketSymbol
    interval: HistoricalInterval
    direction: Directional
    decision_time: AwareDatetime
    source_bar_open_time: AwareDatetime
    holding_period_bars: PositiveCount
    backtest_settings_id: Identifier
    entry_time: AwareDatetime | None = None
    exit_time: AwareDatetime | None = None
    entry_price_raw: PositiveDecimal | None = None
    exit_price_raw: PositiveDecimal | None = None
    returns: OutcomeReturns | None = None
    favorable_excursion: NonnegativeDecimal | None = None
    adverse_excursion: Annotated[Decimal, Field(le=0)] | None = None
    status: BacktestOutcomeStatus
    reason: OutcomeReason

    @model_validator(mode="after")
    def coherent_outcome(self) -> Self:
        if self.source_bar_open_time >= self.decision_time:
            raise ValueError("decision must follow its source bar open")
        if (self.entry_time is None) != (self.entry_price_raw is None):
            raise ValueError("entry time and raw price must appear together")
        if self.entry_time is not None and self.entry_time < self.decision_time:
            raise ValueError("entry cannot precede decision")
        if self.status == BacktestOutcomeStatus.COMPLETED:
            if (self.entry_time is None or self.exit_time is None or self.exit_price_raw is None
                    or self.returns is None or self.favorable_excursion is None or self.adverse_excursion is None
                    or self.reason != OutcomeReason.HORIZON_COMPLETED):
                raise ValueError("completed outcomes require an entry, exit and returns")
            if self.exit_time <= self.entry_time:
                raise ValueError("exit must follow entry")
        elif (self.exit_time is not None or self.exit_price_raw is not None or self.returns is not None
              or self.favorable_excursion is not None or self.adverse_excursion is not None
              or self.reason == OutcomeReason.HORIZON_COMPLETED):
            raise ValueError("incomplete outcomes cannot invent an exit or returns")
        if self.reason == OutcomeReason.MISSING_ENTRY_BAR and self.entry_time is not None:
            raise ValueError("missing entry cannot have entry values")
        if self.reason == OutcomeReason.MISSING_HORIZON_BAR and self.entry_time is None:
            raise ValueError("missing horizon requires an observed entry")
        return self


class HistoricalDecision(BacktestModel):
    """One sampled decision, with its source bar and optional numeric regime."""

    source_bar_open_time: AwareDatetime
    source_bar_close_time: AwareDatetime
    decision: DecisionRecord
    regime: RegimeFeatures | None = None

    @model_validator(mode="after")
    def source_precedes_decision(self) -> Self:
        if not self.source_bar_open_time < self.source_bar_close_time <= self.decision.generated_at:
            raise ValueError("historical decision cannot precede its completed source bar")
        return self


class NormalizedCurvePoint(BacktestModel):
    index: Count
    outcome_id: Identifier | None
    exit_time: AwareDatetime | None
    cumulative_net_return: Decimal
    normalized_value: Decimal
    drawdown: NonnegativeDecimal


class BacktestMetrics(BacktestModel):
    evaluated_decision_count: Count
    eligible_count: Count
    blocked_count: Count
    no_action_count: Count
    completed_count: Count
    incomplete_count: Count
    boundary_censored_count: Count = 0
    long_count: Count
    short_count: Count
    win_count: Count
    loss_count: Count
    flat_count: Count
    win_rate: Annotated[Decimal, Field(ge=0, le=1)] | None
    mean_gross_return: Decimal | None
    mean_net_return: Decimal | None
    median_net_return: Decimal | None
    sum_gross_returns: Decimal
    sum_simulated_costs: NonnegativeDecimal
    sum_net_returns: Decimal
    gross_profit: NonnegativeDecimal
    gross_loss: NonnegativeDecimal
    profit_factor: NonnegativeDecimal | None
    profit_factor_state: Literal["defined", "no_losses", "no_nonflat_outcomes", "no_completed_outcomes"]
    best_net_return: Decimal | None
    worst_net_return: Decimal | None
    max_consecutive_wins: Count
    max_consecutive_losses: Count
    normalized_curve: tuple[NormalizedCurvePoint, ...]
    normalized_max_drawdown: NonnegativeDecimal

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if self.evaluated_decision_count != self.eligible_count + self.blocked_count + self.no_action_count:
            raise ValueError("decision counts must reconcile")
        if self.eligible_count != self.completed_count + self.incomplete_count:
            raise ValueError("each eligible decision must have one completed or incomplete outcome")
        if self.eligible_count != self.long_count + self.short_count:
            raise ValueError("eligible directions must reconcile")
        if self.completed_count != self.win_count + self.loss_count + self.flat_count:
            raise ValueError("completed classifications must reconcile")
        if self.boundary_censored_count > self.incomplete_count:
            raise ValueError("boundary censoring is a subset of incomplete outcomes")
        return self


class BacktestCohortMetrics(BacktestModel):
    key: Identifier
    metrics: BacktestMetrics


class BacktestTimeSegment(BacktestModel):
    index: Count
    start: AwareDatetime
    end: AwareDatetime
    includes_end: bool
    metrics: BacktestMetrics


class BacktestRunMetadata(BacktestModel):
    run_id: Identifier
    dataset_id: Identifier
    engine_version: Identifier
    started_from: AwareDatetime | None
    ended_at: AwareDatetime | None
    symbols: tuple[MarketSymbol, ...]
    interval: HistoricalInterval
    input_count: Count
    duplicate_decision_reads: Count
    feature_settings_id: Identifier
    strategy_settings_id: Identifier
    decision_policy_id: Identifier
    backtest_settings_id: Identifier


class BacktestRunReport(BacktestModel):
    metadata: BacktestRunMetadata
    decisions: tuple[HistoricalDecision, ...]
    outcomes: tuple[BacktestSignalOutcome, ...]
    metrics: BacktestMetrics
    per_symbol: tuple[BacktestCohortMetrics, ...]
    per_direction: tuple[BacktestCohortMetrics, ...]
    per_decision_outcome: tuple[BacktestCohortMetrics, ...]
    per_strategy_coverage: tuple[BacktestCohortMetrics, ...]
    chronological_segments: tuple[BacktestTimeSegment, ...]
    limitations: tuple[str, ...]
