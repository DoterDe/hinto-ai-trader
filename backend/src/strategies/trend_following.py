from decimal import Decimal

from src.application.strategy_settings import MIN_TREND_CORROBORATION, TREND_COMPONENT_WEIGHTS, StrategySettings
from src.domain.features import FeatureSnapshot
from src.domain.strategies import StrategyEvidence, StrategyId
from src.strategies.base import Strategy, context, contribution, require_range, volatility_quality
from src.strategies.scoring import arithmetic, linear_quality, sign, signed_score


class TrendFollowing(Strategy):
    strategy_id = StrategyId.TREND
    required_feature_groups = ("trend", "momentum", "regime", "volatility")

    @arithmetic
    def calculate(self, snapshot: FeatureSnapshot, settings: StrategySettings) -> tuple[StrategyEvidence, ...]:
        trend, momentum, regime = snapshot.trend.values, snapshot.momentum.values, snapshot.regime.values
        for value in (trend.ema_fast, trend.ema_slow, trend.ema_long):
            require_range(value, Decimal(0), exclusive_low=True)
        require_range(trend.distance_from_slow, Decimal(-1), exclusive_low=True)
        require_range(regime.directional_efficiency, Decimal(0), Decimal(1))
        require_range(momentum.roc_percent, Decimal(-100))
        fast_slow = (trend.ema_fast - trend.ema_slow) / trend.ema_slow
        slow_long = (trend.ema_slow - trend.ema_long) / trend.ema_long
        inputs = (
            ("fast_slow_separation", fast_slow, signed_score(fast_slow, settings.ema_separation_dead_zone, settings.ema_separation_saturation), TREND_COMPONENT_WEIGHTS[0], settings.ema_separation_saturation),
            ("slow_long_separation", slow_long, signed_score(slow_long, settings.ema_separation_dead_zone, settings.ema_separation_saturation), TREND_COMPONENT_WEIGHTS[1], settings.ema_separation_saturation),
            ("slow_ema_distance", trend.distance_from_slow, signed_score(trend.distance_from_slow, settings.price_distance_dead_zone, settings.price_distance_saturation), TREND_COMPONENT_WEIGHTS[2], settings.price_distance_saturation),
            ("roc_percent", momentum.roc_percent, signed_score(momentum.roc_percent, settings.roc_dead_zone, settings.roc_saturation), TREND_COMPONENT_WEIGHTS[3], settings.roc_saturation),
        )
        raw = sum((normalized * weight for _, _, normalized, weight, _ in inputs), Decimal(0))
        supporters = sum(sign(normalized) == sign(raw) and normalized != 0 for _, _, normalized, _, _ in inputs)
        corroboration = Decimal(int(supporters >= MIN_TREND_CORROBORATION))
        efficiency = linear_quality(regime.directional_efficiency, settings.trend_efficiency_floor,
                                    settings.strong_trend_efficiency)
        atr_quality, atr_evidence = volatility_quality(snapshot, settings)
        quality = efficiency * atr_quality * corroboration
        return tuple(contribution(name, value, normalized, weight, quality, reference)
                     for name, value, normalized, weight, reference in inputs) + (
            context("trend_efficiency", regime.directional_efficiency, efficiency, reference=settings.strong_trend_efficiency),
            context("corroborating_components", Decimal(supporters), corroboration, reference=Decimal(MIN_TREND_CORROBORATION)),
            atr_evidence,
        )
