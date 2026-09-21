"""Bounded execution-assumption comparisons for identical historical signals."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from src.domain.backtesting import BacktestMetrics, BacktestModel
from src.domain.models import Identifier

MAX_COST_SCENARIOS = 4
CostBps = Annotated[Decimal, Field(ge=0, le=100)]


class CostScenario(BacktestModel):
    model_version: Literal["phase6-cost-v1"] = "phase6-cost-v1"
    fee_bps_per_side: CostBps
    slippage_bps_per_side: CostBps


class CostScenarioResult(BacktestModel):
    scenario_id: Identifier
    assumptions: CostScenario
    is_baseline: bool = Field(strict=True)
    metrics: BacktestMetrics
    mean_cost_return: Decimal | None
    sign_changed_decision_ids: tuple[Identifier, ...] = Field(max_length=100_000)
    warnings: tuple[Literal["SMALL_SAMPLE", "NO_COMPLETED_OUTCOMES", "INCOMPLETE_OUTCOMES",
                            "NET_SIGN_CHANGED_FROM_BASELINE"], ...]
