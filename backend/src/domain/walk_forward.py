"""Fixed chronological research protocols; context is never parameter fitting."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from src.domain.backtesting import BacktestMetrics, BacktestModel, BacktestSignalOutcome, Count, HistoricalDecision, HistoricalInterval, PositiveCount
from src.domain.historical_dataset import DatasetCoverage, DatasetId, MAX_INPUT_BARS, MAX_SYMBOLS, UtcTime
from src.domain.market_data import MarketSymbol
from src.domain.models import Identifier
from src.domain.validation_regimes import RegimeAssignment

PROTOCOL_VERSION = "walk-forward-v1"
MAX_SPLITS = 256
MAX_REPLAY_ROWS = 200_000
MAX_TEST_ROWS = 100_000
BoundaryCount = Annotated[int, Field(strict=True, gt=0, le=MAX_INPUT_BARS)]
WarningCode = Literal["VALID_WITH_GAPS", "PARTIAL_TEST_WINDOW", "NO_TEST_OBSERVATIONS",
                      "VALID_NO_SIGNALS", "INCOMPLETE_OUTCOMES", "BOUNDARY_CENSORED_OUTCOMES",
                      "OVERLAPPING_TEST_WINDOWS", "SKIPPED_TEST_BOUNDARIES"]


class WalkForwardMode(str, Enum):
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"


class WalkForwardProtocol(BacktestModel):
    version: Literal["walk-forward-v1"] = PROTOCOL_VERSION
    dataset_id: DatasetId
    dataset_schema_version: Literal["historical-dataset-v1"] = "historical-dataset-v1"
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1, max_length=MAX_SYMBOLS)
    interval: HistoricalInterval = "1m"
    mode: WalkForwardMode = WalkForwardMode.EXPANDING
    minimum_context_boundaries: BoundaryCount = 50
    warmup_boundaries: BoundaryCount = 50
    test_boundaries: BoundaryCount = 20
    step_boundaries: BoundaryCount = 20
    rolling_context_boundaries: BoundaryCount | None = None
    allow_test_overlap: bool = Field(default=False, strict=True)
    partial_window: Literal["INCLUDE", "REJECT"] = "INCLUDE"

    @field_validator("symbols")
    @classmethod
    def canonical_scope(cls, symbols: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(symbols)) != len(symbols):
            raise ValueError("protocol symbols must be unique")
        return tuple(sorted(symbols))

    @model_validator(mode="after")
    def coherent_protocol(self) -> Self:
        if self.minimum_context_boundaries < self.warmup_boundaries:
            raise ValueError("minimum context must cover required warmup")
        if self.mode == WalkForwardMode.ROLLING:
            if self.rolling_context_boundaries is None or self.rolling_context_boundaries < self.minimum_context_boundaries:
                raise ValueError("rolling context must cover minimum context and warmup")
        elif self.rolling_context_boundaries is not None:
            raise ValueError("expanding mode cannot specify rolling context")
        if self.allow_test_overlap != (self.step_boundaries < self.test_boundaries):
            raise ValueError("overlapping tests require explicit opt-in and a shorter step")
        return self


class WalkForwardSplit(BacktestModel):
    split_id: Identifier
    ordinal: Count
    dataset_id: DatasetId
    protocol_id: Identifier
    context_start: UtcTime
    context_end: UtcTime
    test_start: UtcTime
    test_end: UtcTime
    # An expanding range can span more missing slots than retained input rows.
    # Split count and replay/evidence budgets bound work independently.
    context_boundary_count: PositiveCount
    test_boundary_count: BoundaryCount
    observed_context_boundaries: Count
    observed_test_boundaries: Count
    required_warmup: BoundaryCount
    context_coverage: tuple[DatasetCoverage, ...] = Field(min_length=1, max_length=MAX_SYMBOLS)
    test_coverage: tuple[DatasetCoverage, ...] = Field(min_length=1, max_length=MAX_SYMBOLS)
    insufficient_context_symbols: tuple[MarketSymbol, ...] = Field(max_length=MAX_SYMBOLS)
    status: Literal["READY", "INSUFFICIENT_CONTEXT", "PARTIAL_WINDOW_REJECTED"]
    warnings: tuple[WarningCode, ...] = ()

    @model_validator(mode="after")
    def coherent_bounds(self) -> Self:
        if not self.context_start < self.context_end == self.test_start < self.test_end:
            raise ValueError("context must precede the disjoint test window")
        if self.observed_context_boundaries > self.context_boundary_count or self.observed_test_boundaries > self.test_boundary_count:
            raise ValueError("observed boundaries exceed declared range")
        if tuple(item.symbol for item in self.context_coverage) != tuple(item.symbol for item in self.test_coverage):
            raise ValueError("context and test scope must match")
        if self.insufficient_context_symbols and self.status != "INSUFFICIENT_CONTEXT":
            raise ValueError("missing warmup evidence must be explicit")
        return self


class WalkForwardPlan(BacktestModel):
    dataset_id: DatasetId
    protocol_id: Identifier
    required_warmup: BoundaryCount
    total_boundary_count: Count
    observed_boundary_count: Count
    status: Literal["READY", "INSUFFICIENT_CONTEXT", "NO_TEST_BOUNDARIES"]
    splits: tuple[WalkForwardSplit, ...] = Field(max_length=MAX_SPLITS)


class WalkForwardEngineIdentity(BacktestModel):
    evaluator_version: Literal["walk-forward-evaluator-v1"] = "walk-forward-evaluator-v1"
    backtest_engine_version: Identifier
    strategy_engine_version: Identifier
    decision_engine_version: Identifier
    feature_settings_id: Identifier
    strategy_settings_id: Identifier
    decision_policy_id: Identifier
    backtest_settings_id: Identifier


class WalkForwardEvidence(BacktestModel):
    """Compact hashes of actual replay frames, not recomputed indicator formulas."""

    symbol: MarketSymbol
    boundary: UtcTime
    bar_id: Identifier
    feature_snapshot_id: Identifier
    strategy_snapshot_id: Identifier
    decision_id: Identifier
    regime: RegimeAssignment


class WalkForwardWindowResult(BacktestModel):
    result_id: Identifier
    split: WalkForwardSplit
    engines: WalkForwardEngineIdentity
    input_content_id: Identifier
    status: Literal["EVALUATED", "INSUFFICIENT_CONTEXT", "PARTIAL_WINDOW_REJECTED"]
    decisions: tuple[HistoricalDecision, ...] = Field(max_length=MAX_TEST_ROWS)
    outcomes: tuple[BacktestSignalOutcome, ...] = Field(max_length=MAX_TEST_ROWS)
    evidence: tuple[WalkForwardEvidence, ...] = Field(max_length=MAX_TEST_ROWS)
    metrics: BacktestMetrics | None
    warnings: tuple[WarningCode, ...] = ()

    @model_validator(mode="after")
    def evidence_matches_status(self) -> Self:
        if self.status == "EVALUATED":
            if self.metrics is None or self.metrics.evaluated_decision_count != len(self.decisions):
                raise ValueError("evaluated windows require reconciled metrics")
            if len(self.evidence) != len(self.decisions):
                raise ValueError("each captured decision requires evidence")
        elif self.metrics is not None or self.decisions or self.outcomes or self.evidence:
            raise ValueError("rejected windows cannot fabricate evaluated evidence")
        return self


class WalkForwardEvaluation(BacktestModel):
    evaluation_id: Identifier
    protocol: WalkForwardProtocol
    plan: WalkForwardPlan
    engines: WalkForwardEngineIdentity
    windows: tuple[WalkForwardWindowResult, ...] = Field(max_length=MAX_SPLITS)
