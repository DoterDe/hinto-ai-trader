from decimal import Decimal

from src.application.strategy_settings import REVERSION_COMPONENT_WEIGHTS, StrategySettings
from src.domain.features import FeatureSnapshot
from src.domain.strategies import StrategyEvidence, StrategyId
from src.strategies.base import Strategy, context, contribution, require_range, volatility_quality
from src.strategies.scoring import arithmetic, dead_zone_score, linear_quality, sign, signed_score


class MeanReversion(Strategy):
    strategy_id = StrategyId.MEAN_REVERSION
    required_feature_groups = ("trend", "momentum", "volatility", "regime")
    optional_feature_groups = ("microstructure",)

    @arithmetic
    def calculate(self, snapshot: FeatureSnapshot, settings: StrategySettings) -> tuple[StrategyEvidence, ...]:
        trend, momentum = snapshot.trend.values, snapshot.momentum.values
        regime, volatility = snapshot.regime.values, snapshot.volatility.values
        require_range(momentum.rsi, Decimal(0), Decimal(100))
        require_range(volatility.normalized_atr, Decimal(0), exclusive_low=True)
        require_range(regime.directional_efficiency, Decimal(0), Decimal(1))
        require_range(regime.relative_volume, Decimal(0))
        for distance in (trend.distance_from_fast, trend.distance_from_slow):
            require_range(distance, Decimal(-1), exclusive_low=True)
        stretch = trend.distance_from_slow / volatility.normalized_atr
        stretch_score = -signed_score(stretch, settings.reversion_stretch_dead_zone, settings.reversion_stretch_saturation)
        rsi_score = -dead_zone_score(momentum.rsi, settings.rsi_extreme_low, settings.rsi_neutral_low,
                                     settings.rsi_neutral_high, settings.rsi_extreme_high)
        confirmation = Decimal(int(stretch_score != 0 and sign(trend.distance_from_fast) == sign(stretch)))
        weak_trend = 1 - linear_quality(regime.directional_efficiency, settings.trend_efficiency_floor,
                                       settings.strong_trend_efficiency)
        quiet_volume = 1 - linear_quality(regime.relative_volume, settings.relative_volume_baseline,
                                         settings.relative_volume_exhaustion)
        atr_quality, atr_evidence = volatility_quality(snapshot, settings)
        quality = weak_trend * quiet_volume * atr_quality * confirmation
        return (
            contribution("slow_ema_stretch_atr", stretch, stretch_score, REVERSION_COMPONENT_WEIGHTS[0], quality, settings.reversion_stretch_saturation),
            contribution("rsi_reversion", momentum.rsi, rsi_score, REVERSION_COMPONENT_WEIGHTS[1], quality, settings.rsi_neutral_high),
            context("weak_trend_quality", regime.directional_efficiency, weak_trend, reference=settings.strong_trend_efficiency),
            context("quiet_volume_quality", regime.relative_volume, quiet_volume, reference=settings.relative_volume_exhaustion),
            context("fast_distance_confirmation", trend.distance_from_fast, confirmation, reference=Decimal(0)),
            atr_evidence,
        )
