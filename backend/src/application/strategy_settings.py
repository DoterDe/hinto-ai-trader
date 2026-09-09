"""Engineering defaults for analytical scoring, never profitability estimates."""

from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.strategies import StrategyId

Positive = Annotated[Decimal, Field(gt=0)]
Nonnegative = Annotated[Decimal, Field(ge=0)]
Unit = Annotated[Decimal, Field(ge=0, le=1)]
Percent = Annotated[Decimal, Field(ge=0, le=100)]

# Fixed component weights are part of the versioned algorithms, not tuning knobs.
TREND_COMPONENT_WEIGHTS = tuple(map(Decimal, (30, 30, 20, 20)))
MOMENTUM_COMPONENT_WEIGHTS = tuple(map(Decimal, (40, 25, 20, 15)))
REVERSION_COMPONENT_WEIGHTS = tuple(map(Decimal, (60, 40)))
MIN_TREND_CORROBORATION = 2


class StrategySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRATEGY_", frozen=True,
                                     allow_inf_nan=False, validate_default=True,
                                     revalidate_instances="always", extra="ignore")

    enabled_strategies: tuple[StrategyId, ...] = tuple(StrategyId)
    min_absolute_strategy_score: Annotated[Decimal, Field(gt=0, le=100)] = Decimal(25)
    candidate_score_threshold: Annotated[Decimal, Field(gt=0, le=100)] = Decimal(40)
    min_candidate_confidence: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.55")
    rsi_neutral_low: Percent = Decimal(45)
    rsi_neutral_high: Percent = Decimal(55)
    rsi_extreme_low: Percent = Decimal(30)
    rsi_extreme_high: Percent = Decimal(70)
    max_acceptable_spread_bps: Positive = Decimal(15)
    trend_efficiency_floor: Unit = Decimal("0.25")
    strong_trend_efficiency: Unit = Decimal("0.55")
    relative_volume_baseline: Positive = Decimal(1)
    relative_volume_exhaustion: Positive = Decimal(3)
    ema_separation_dead_zone: Nonnegative = Decimal("0.0005")
    ema_separation_saturation: Positive = Decimal("0.005")
    price_distance_dead_zone: Nonnegative = Decimal("0.001")
    price_distance_saturation: Positive = Decimal("0.01")
    roc_dead_zone: Nonnegative = Decimal("0.1")
    roc_saturation: Positive = Decimal(2)
    taker_bias_dead_zone: Unit = Decimal("0.1")
    taker_bias_saturation: Unit = Decimal("0.6")
    reversion_stretch_dead_zone: Nonnegative = Decimal(1)
    reversion_stretch_saturation: Positive = Decimal(3)
    atr_soft_limit: Positive = Decimal("0.025")
    atr_hard_limit: Positive = Decimal("0.05")
    optional_context_missing_quality: Unit = Decimal("0.75")
    max_feature_age_seconds: Positive = Decimal(10)
    trend_weight: Annotated[Decimal, Field(gt=0, le=100)] = Decimal(1)
    momentum_weight: Annotated[Decimal, Field(gt=0, le=100)] = Decimal(1)
    mean_reversion_weight: Annotated[Decimal, Field(gt=0, le=100)] = Decimal(1)

    @model_validator(mode="after")
    def coherent_thresholds(self) -> Self:
        if not self.enabled_strategies or len(set(self.enabled_strategies)) != len(self.enabled_strategies):
            raise ValueError("enabled_strategies must be nonempty and unique")
        if self.candidate_score_threshold < self.min_absolute_strategy_score:
            raise ValueError("candidate score threshold must cover the strategy dead zone")
        if not 0 < self.rsi_extreme_low < self.rsi_neutral_low < self.rsi_neutral_high < self.rsi_extreme_high < 100:
            raise ValueError("RSI thresholds must be ordered strictly within 0..100")
        for low, high in ((self.trend_efficiency_floor, self.strong_trend_efficiency),
                          (self.relative_volume_baseline, self.relative_volume_exhaustion),
                          (self.ema_separation_dead_zone, self.ema_separation_saturation),
                          (self.price_distance_dead_zone, self.price_distance_saturation),
                          (self.roc_dead_zone, self.roc_saturation),
                          (self.taker_bias_dead_zone, self.taker_bias_saturation),
                          (self.reversion_stretch_dead_zone, self.reversion_stretch_saturation),
                          (self.atr_soft_limit, self.atr_hard_limit)):
            if low >= high:
                raise ValueError("lower scoring thresholds must precede upper thresholds")
        return self

    def weight(self, strategy_id: StrategyId) -> Decimal:
        return {StrategyId.TREND: self.trend_weight, StrategyId.MOMENTUM: self.momentum_weight,
                StrategyId.MEAN_REVERSION: self.mean_reversion_weight}[strategy_id]
