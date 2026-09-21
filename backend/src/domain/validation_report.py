"""Content-addressed offline validation evidence; no executable configuration."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from src.domain.backtesting import BacktestMetrics, BacktestModel, PositiveCount
from src.domain.historical_dataset import HistoricalDatasetManifest, UtcTime
from src.domain.models import Identifier
from src.domain.validation_costs import MAX_COST_SCENARIOS, CostBps, CostScenarioResult
from src.domain.validation_regimes import RegimeAnalysis
from src.domain.walk_forward import MAX_SPLITS, WalkForwardEvaluation

REPORT_VERSION = "validation-report-v1"
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_REPORT_DECISIONS = 20_000
MAX_REPORT_GROUPS = 4_096
ReportId = Annotated[str, StringConstraints(pattern=r"^validation_report_[0-9a-f]{64}$")]


class ValidationCostBaseline(BacktestModel):
    holding_period_bars: PositiveCount
    fee_bps_per_side: CostBps
    slippage_bps_per_side: CostBps
    chronological_segments: Annotated[int, Field(strict=True, ge=1, le=100)]


class ValidationAnalysis(BacktestModel):
    metrics: BacktestMetrics
    regimes: RegimeAnalysis
    costs: tuple[CostScenarioResult, ...] = Field(min_length=1, max_length=MAX_COST_SCENARIOS)


class ValidationWindowAnalysis(BacktestModel):
    window_result_id: Identifier
    analysis: ValidationAnalysis | None


class ValidationReport(BacktestModel):
    schema_version: Literal["validation-report-v1"] = REPORT_VERSION
    report_id: ReportId
    content_checksum: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    mode: Literal["PAPER / VIRTUAL / RESEARCH ONLY"] = "PAPER / VIRTUAL / RESEARCH ONLY"
    dataset: HistoricalDatasetManifest
    evaluation: WalkForwardEvaluation
    cost_baseline: ValidationCostBaseline
    windows: tuple[ValidationWindowAnalysis, ...] = Field(max_length=MAX_SPLITS)
    aggregate: ValidationAnalysis | None
    warnings: tuple[Identifier, ...] = Field(max_length=32)
    limitations: tuple[Annotated[str, Field(max_length=500)], ...] = Field(max_length=16)
    generated_at: UtcTime | None = None
