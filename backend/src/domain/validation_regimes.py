"""Descriptive, fixed causal partitions; never strategy inputs or predictions."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from src.domain.backtesting import BacktestMetrics, BacktestModel, Count
from src.domain.historical_dataset import MAX_SYMBOLS, UtcTime
from src.domain.market_data import MarketSymbol
from src.domain.models import Identifier

TrendLabel = Literal["UPTREND", "DOWNTREND", "RANGE", "UNKNOWN"]
VolatilityLabel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
TRENDS = ("UPTREND", "DOWNTREND", "RANGE", "UNKNOWN")
VOLATILITIES = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")


class RegimeDefinition(BacktestModel):
    # Versioned engineering thresholds, not estimated from research returns.
    version: Literal["causal-regimes-v1"] = "causal-regimes-v1"
    ema_separation_deadband: Literal[Decimal("0.0005")] = Decimal("0.0005")
    directional_efficiency_floor: Literal[Decimal("0.25")] = Decimal("0.25")
    normalized_atr_low_upper: Literal[Decimal("0.005")] = Decimal("0.005")
    normalized_atr_medium_upper: Literal[Decimal("0.02")] = Decimal("0.02")
    minimum_completed_samples: Literal[30] = 30

    @field_validator("ema_separation_deadband", "directional_efficiency_floor", "normalized_atr_low_upper",
                     "normalized_atr_medium_upper", mode="before")
    @classmethod
    def exact_decimal_literal(cls, value):
        return Decimal(value) if isinstance(value, str) else value


class RegimeAssignment(BacktestModel):
    assignment_id: Identifier
    definition_id: Identifier
    symbol: MarketSymbol
    boundary: UtcTime
    evidence_boundary: UtcTime | None
    trend: TrendLabel
    volatility: VolatilityLabel
    normalized_ema_separation: Decimal | None
    directional_efficiency: Decimal | None
    normalized_atr: Decimal | None
    unknown_reasons: tuple[Literal["EVIDENCE_BOUNDARY_MISMATCH", "TREND_EVIDENCE_UNAVAILABLE",
                                   "VOLATILITY_EVIDENCE_UNAVAILABLE"], ...]


class SampleSummary(BacktestModel):
    count: Count
    minimum: Decimal | None
    maximum: Decimal | None
    mean: Decimal | None


class RegimeGroup(BacktestModel):
    dimension: Literal["symbol", "trend", "volatility"]
    key: Identifier
    metrics: BacktestMetrics
    confidence: SampleSummary
    composite_score: SampleSummary
    warnings: tuple[Literal["EMPTY_GROUP", "SMALL_SAMPLE", "INCOMPLETE_OUTCOMES"], ...]


class RegimeAnalysis(BacktestModel):
    definition_id: Identifier
    definition: RegimeDefinition
    groups: tuple[RegimeGroup, ...] = Field(max_length=MAX_SYMBOLS + len(TRENDS) + len(VOLATILITIES))
