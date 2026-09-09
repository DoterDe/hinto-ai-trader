from decimal import Decimal

from src.application.strategy_settings import MOMENTUM_COMPONENT_WEIGHTS, StrategySettings
from src.domain.features import FeatureSnapshot
from src.domain.strategies import StrategyEvidence, StrategyId
from src.strategies.base import Strategy, context, contribution, require_range
from src.strategies.scoring import arithmetic, dead_zone_score, linear_quality, signed_score


class MomentumContinuation(Strategy):
    strategy_id = StrategyId.MOMENTUM
    required_feature_groups = ("momentum", "volume")
    optional_feature_groups = ("microstructure",)

    @arithmetic
    def calculate(self, snapshot: FeatureSnapshot, settings: StrategySettings) -> tuple[StrategyEvidence, ...]:
        momentum, volume = snapshot.momentum.values, snapshot.volume.values
        require_range(momentum.rsi, Decimal(0), Decimal(100))
        require_range(momentum.roc_percent, Decimal(-100))
        require_range(volume.relative_volume, Decimal(0))
        require_range(volume.taker_buy_ratio, Decimal(0), Decimal(1))
        require_range(volume.rolling_vwap, Decimal(0), exclusive_low=True)
        change = momentum.close_change / volume.rolling_vwap
        taker_bias = 2 * volume.taker_buy_ratio - 1
        volume_quality = linear_quality(volume.relative_volume, 0, settings.relative_volume_baseline)
        exhaustion = 1 - max(linear_quality(momentum.rsi, settings.rsi_extreme_high, 100),
                             linear_quality(-momentum.rsi, -settings.rsi_extreme_low, 0))
        quality = volume_quality * exhaustion
        inputs = (
            ("roc_percent", momentum.roc_percent, signed_score(momentum.roc_percent, settings.roc_dead_zone, settings.roc_saturation), MOMENTUM_COMPONENT_WEIGHTS[0], settings.roc_saturation),
            ("rsi_continuation", momentum.rsi, dead_zone_score(momentum.rsi, settings.rsi_extreme_low, settings.rsi_neutral_low, settings.rsi_neutral_high, settings.rsi_extreme_high), MOMENTUM_COMPONENT_WEIGHTS[1], settings.rsi_neutral_high),
            ("close_change_over_vwap", change, signed_score(change, settings.price_distance_dead_zone, settings.price_distance_saturation), MOMENTUM_COMPONENT_WEIGHTS[2], settings.price_distance_saturation),
            ("taker_buy_bias", taker_bias, signed_score(taker_bias, settings.taker_bias_dead_zone, settings.taker_bias_saturation), MOMENTUM_COMPONENT_WEIGHTS[3], settings.taker_bias_saturation),
        )
        return tuple(contribution(name, value, normalized, weight, quality, reference)
                     for name, value, normalized, weight, reference in inputs) + (
            context("relative_volume_quality", volume.relative_volume, volume_quality, reference=settings.relative_volume_baseline),
            context("rsi_exhaustion_quality", momentum.rsi, exhaustion, reference=settings.rsi_extreme_high),
            context("taker_base_volume_delta_proxy", volume.taker_base_volume_delta_proxy, None, code="candle_proxy_only"),
        )
