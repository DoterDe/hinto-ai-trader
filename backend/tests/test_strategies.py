from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from src.application.strategy_settings import StrategySettings
from src.domain.features import FeatureSnapshot, Readiness
from src.domain.strategies import StrategyDirection, StrategyReadiness
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import MomentumContinuation
from src.strategies.trend_following import TrendFollowing
from strategy_fixtures import NOW, features, positive_momentum, positive_stretch, positive_trend, state

STRATEGIES = (TrendFollowing(), MomentumContinuation(), MeanReversion())


def assess(strategy, snapshot, **kwargs):
    return strategy.evaluate(snapshot, StrategySettings(), **kwargs)


@pytest.mark.parametrize("direction", [1, -1])
def test_aligned_trend_has_four_explained_contributions(direction: int) -> None:
    snapshot = positive_trend() if direction == 1 else features(
        trend=dict(ema_fast="98", ema_slow="99", ema_long="100", distance_from_slow="-0.02"),
        momentum=dict(roc_percent="-2"), regime=dict(directional_efficiency="0.55"))
    result = assess(TrendFollowing(), snapshot)
    assert result.readiness == StrategyReadiness.READY
    assert result.score == 100 * direction
    assert result.confidence == 1
    assert [item.contribution for item in result.evidence if item.weight] == [30 * direction, 30 * direction, 20 * direction, 20 * direction]


def test_contradictory_ema_structure_offsets_score_and_confidence() -> None:
    snapshot = positive_trend()
    trend = snapshot.trend.values.model_copy(update={"ema_slow": Decimal(99)})
    snapshot = snapshot.model_copy(update={"trend": snapshot.trend.model_copy(update={"values": trend})})
    result = assess(TrendFollowing(), snapshot)
    assert result.score == 40  # 30 - 30 + 20 + 20.
    assert result.confidence == Decimal("0.16")  # strength .4 * agreement .4.


@pytest.mark.parametrize("efficiency,score", [("0.25", 0), ("0.4", 50), ("0.55", 100)])
def test_efficiency_quality_thresholds(efficiency: str, score: int) -> None:
    snapshot = positive_trend()
    regime = snapshot.regime.values.model_copy(update={"directional_efficiency": Decimal(efficiency)})
    result = assess(TrendFollowing(), snapshot.model_copy(update={"regime": snapshot.regime.model_copy(update={"values": regime})}))
    assert result.score == score
    assert result.confidence == Decimal(score) / 100


def test_one_ema_cross_is_insufficient() -> None:
    result = assess(TrendFollowing(), features(trend=dict(ema_fast="102"), regime=dict(directional_efficiency="0.8")))
    assert result.score == result.confidence == 0
    assert result.direction == StrategyDirection.NEUTRAL


@pytest.mark.parametrize("direction", [1, -1])
def test_momentum_continuation_requires_combined_evidence(direction: int) -> None:
    snapshot = positive_momentum() if direction == 1 else features(
        momentum=dict(roc_percent="-2", rsi="30", close_change="-1"),
        volume=dict(relative_volume="2", taker_buy_ratio="0.2", taker_base_volume_delta_proxy="-6"))
    result = assess(MomentumContinuation(), snapshot)
    assert result.score == 100 * direction
    assert result.confidence == 1
    assert [item.contribution for item in result.evidence if item.weight] == [40 * direction, 25 * direction, 20 * direction, 15 * direction]


@pytest.mark.parametrize("rsi,expected", [("70", 100), ("85", 50), ("100", 0)])
def test_extreme_rsi_reduces_continuation_conviction(rsi: str, expected: int) -> None:
    snapshot = positive_momentum()
    momentum = snapshot.momentum.values.model_copy(update={"rsi": Decimal(rsi)})
    result = assess(MomentumContinuation(), snapshot.model_copy(update={"momentum": snapshot.momentum.model_copy(update={"values": momentum})}))
    assert result.score == expected
    assert result.confidence == Decimal(expected) / 100


@pytest.mark.parametrize("relative,expected", [("0", 0), ("0.5", 50), ("1", 100), ("2", 100)])
def test_volume_quality_is_bounded_and_does_not_supply_direction(relative: str, expected: int) -> None:
    snapshot = positive_momentum()
    volume = snapshot.volume.values.model_copy(update={"relative_volume": Decimal(relative)})
    result = assess(MomentumContinuation(), snapshot.model_copy(update={"volume": snapshot.volume.model_copy(update={"values": volume})}))
    assert result.score == expected
    assert assess(MomentumContinuation(), features(volume=dict(relative_volume=relative))).score == 0


@pytest.mark.parametrize("direction", [1, -1])
def test_reversion_opposes_stretch_only_in_weak_trend(direction: int) -> None:
    snapshot = positive_stretch() if direction == 1 else features(
        trend=dict(distance_from_slow="-0.03", distance_from_fast="-0.02"),
        momentum=dict(rsi="30"), regime=dict(directional_efficiency="0.25"))
    result = assess(MeanReversion(), snapshot)
    assert result.score == -100 * direction
    assert result.confidence == 1


@pytest.mark.parametrize("efficiency,score", [("0.25", -100), ("0.4", -50), ("0.55", 0), ("1", 0)])
def test_strong_efficiency_suppresses_mean_reversion(efficiency: str, score: int) -> None:
    snapshot = positive_stretch()
    regime = snapshot.regime.values.model_copy(update={"directional_efficiency": Decimal(efficiency)})
    result = assess(MeanReversion(), snapshot.model_copy(update={"regime": snapshot.regime.model_copy(update={"values": regime})}))
    assert result.score == score


def test_reversion_needs_stretch_and_matching_fast_distance() -> None:
    for trend in (dict(distance_from_slow="0.01", distance_from_fast="0.01"),
                  dict(distance_from_slow="0.03", distance_from_fast="-0.01")):
        result = assess(MeanReversion(), features(trend=trend, momentum=dict(rsi="70"),
                                                regime=dict(directional_efficiency="0.25")))
        assert result.score == 0


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_neutral_market_has_explicit_dead_zone(strategy) -> None:
    result = assess(strategy, features())
    assert result.readiness == StrategyReadiness.READY
    assert result.direction == StrategyDirection.NEUTRAL
    assert result.score == result.confidence == 0
    assert "below_strategy_dead_zone" in result.reasons


@pytest.mark.parametrize("strategy,name", [(strategy, name) for strategy in STRATEGIES for name in strategy.required_feature_groups])
@pytest.mark.parametrize("readiness", [Readiness.STALE, Readiness.UNAVAILABLE, Readiness.WARMING_UP])
def test_each_hard_dependency_preserves_its_unready_state(strategy, name, readiness) -> None:
    result = assess(strategy, state(features(), name, readiness))
    assert result.readiness.value == readiness.value
    assert result.score is result.confidence is None
    assert result.direction == StrategyDirection.NEUTRAL
    assert f"{name}:{readiness.value}" in result.reasons


@pytest.mark.parametrize("strategy,snapshot", [(MomentumContinuation(), positive_momentum()), (MeanReversion(), positive_stretch())])
@pytest.mark.parametrize("readiness", [Readiness.STALE, Readiness.UNAVAILABLE, Readiness.WARMING_UP])
def test_missing_optional_book_preserves_score_but_reduces_confidence(strategy, snapshot, readiness) -> None:
    result = assess(strategy, state(snapshot, "microstructure", readiness))
    assert result.readiness == StrategyReadiness.READY
    assert abs(result.score) == 100
    assert result.confidence == Decimal("0.75")
    assert any("optional_" in reason for reason in result.reasons)


def test_known_wide_spread_reduces_optional_confidence_to_zero() -> None:
    snapshot = positive_momentum()
    book = snapshot.microstructure.values.model_copy(update={"spread_bps": Decimal(15)})
    result = assess(MomentumContinuation(), snapshot.model_copy(update={"microstructure": snapshot.microstructure.model_copy(update={"values": book})}))
    assert result.score == 100
    assert result.confidence == 0


def test_unrelated_stale_feature_does_not_invalidate_strategy() -> None:
    result = assess(MomentumContinuation(), state(positive_momentum(), "trend", Readiness.STALE))
    assert result.score == 100
    assert result.readiness == StrategyReadiness.READY


@pytest.mark.parametrize("seconds,reason", [(10, "snapshot_too_old"), (-1, "snapshot_clock_skew")])
def test_old_or_future_snapshot_is_not_scored(seconds: int, reason: str) -> None:
    result = assess(TrendFollowing(), positive_trend(), now=NOW + timedelta(seconds=seconds))
    assert result.readiness == StrategyReadiness.STALE
    assert result.reasons == (reason,)
    assert result.score is None


@pytest.mark.parametrize("field,delta", [("event_time", -10), ("received_at", -10), ("event_time", 1), ("received_at", 1)])
def test_source_timestamps_are_checked_even_when_group_claims_ready(field: str, delta: int) -> None:
    snapshot = positive_trend()
    source = snapshot.sources[0].model_copy(update={field: NOW + timedelta(seconds=delta)})
    result = assess(TrendFollowing(), snapshot.model_copy(update={"sources": (source, *snapshot.sources[1:])}))
    assert result.readiness == StrategyReadiness.STALE
    assert result.score is None


def test_future_closed_candle_is_not_looked_ahead() -> None:
    result = assess(MeanReversion(), positive_stretch().model_copy(update={"closed_candle_time": NOW + timedelta(seconds=1)}))
    assert result.readiness == StrategyReadiness.STALE


@pytest.mark.parametrize("strategy,group,field,value", [
    (TrendFollowing(), "trend", "ema_slow", "0"),
    (TrendFollowing(), "regime", "directional_efficiency", "1.01"),
    (MomentumContinuation(), "momentum", "rsi", "101"),
    (MomentumContinuation(), "volume", "rolling_vwap", "0"),
    (MomentumContinuation(), "volume", "taker_buy_ratio", "-0.1"),
    (MeanReversion(), "volatility", "normalized_atr", "0"),
])
def test_invalid_semantic_values_are_unavailable(strategy, group: str, field: str, value: str) -> None:
    result = assess(strategy, features(**{group: {field: value}}))
    assert result.readiness == StrategyReadiness.UNAVAILABLE
    assert result.reasons == ("invalid_feature_values",)
    assert result.score is None


def test_nonfinite_copies_are_revalidated_instead_of_scored() -> None:
    snapshot = features()
    bad = snapshot.momentum.values.model_copy(update={"rsi": Decimal("NaN")})
    with pytest.raises(ValidationError):
        assess(MomentumContinuation(), snapshot.model_copy(update={"momentum": snapshot.momentum.model_copy(update={"values": bad})}))


def test_deterministic_results_ignore_ambient_decimal_context() -> None:
    snapshot = positive_trend()
    expected = assess(TrendFollowing(), snapshot)
    with localcontext() as context:
        context.prec = 2
        actual = assess(TrendFollowing(), snapshot)
    assert actual == expected
    assert actual.model_dump_json() == expected.model_dump_json()


def test_exact_strategy_dead_zone_boundary() -> None:
    snapshot = positive_trend()
    regime = snapshot.regime.values.model_copy(update={"directional_efficiency": Decimal("0.325")})
    result = assess(TrendFollowing(), snapshot.model_copy(update={"regime": snapshot.regime.model_copy(update={"values": regime})}))
    assert result.score == 25
    assert result.direction == StrategyDirection.LONG


def test_validation_bypassing_settings_copies_are_rejected() -> None:
    config = StrategySettings().model_copy(update={"roc_saturation": Decimal(0)})
    with pytest.raises(ValidationError):
        TrendFollowing().evaluate(features(), config)


@pytest.mark.parametrize("strategy", [TrendFollowing(), MomentumContinuation()])
def test_impossible_negative_price_return_does_not_saturate_to_direction(strategy) -> None:
    result = assess(strategy, features(momentum=dict(roc_percent="-200")))
    assert result.score is None
    assert result.readiness == StrategyReadiness.UNAVAILABLE


@pytest.mark.parametrize("strategy,group,values", [
    (TrendFollowing(), "trend", dict(ema_fast="1e999999", ema_slow="1e-999999")),
    (MomentumContinuation(), "momentum", dict(close_change="1e1000002")),
    (MeanReversion(), "trend", dict(distance_from_slow="1e1000000")),
])
def test_unrepresentable_ratio_is_unavailable_without_nonfinite_output(strategy, group, values) -> None:
    result = assess(strategy, features(**{group: values}))
    assert result.readiness == "unavailable" and result.score is None
    assert "NaN" not in result.model_dump_json() and "Infinity" not in result.model_dump_json()


def test_underflow_during_confidence_calculation_returns_unavailable() -> None:
    snapshot = state(positive_momentum(), "microstructure", Readiness.UNAVAILABLE)
    # Volume halves score/strength; multiplying the tiny optional quality
    # would round an unrepresentable confidence to zero without the trap.
    volume = snapshot.volume.model_copy(update={"values": snapshot.volume.values.model_copy(update={"relative_volume": Decimal("0.5")})})
    snapshot = snapshot.model_copy(update={"volume": volume})
    result = MomentumContinuation().evaluate(snapshot, StrategySettings(optional_context_missing_quality="1e-1000032"))
    assert result.readiness == "unavailable" and result.score is None


def test_extreme_but_representable_ratio_saturates_with_bounded_score() -> None:
    result = assess(MomentumContinuation(), features(momentum=dict(close_change="1e1000000")))
    assert result.readiness == "ready"
    assert result.score == 20 and result.confidence == Decimal("0.2")
    assert result.direction == "NEUTRAL"


@pytest.mark.parametrize("atr,score", [("0.025", 100), ("0.0375", 50), ("0.05", 0), ("1000000", 0)])
def test_atr_quality_has_explicit_linear_limits(atr: str, score: int) -> None:
    snapshot = positive_trend()
    group = snapshot.volatility.model_copy(update={"values": snapshot.volatility.values.model_copy(update={"normalized_atr": Decimal(atr)})})
    assert assess(TrendFollowing(), snapshot.model_copy(update={"volatility": group})).score == score


@pytest.mark.parametrize("rsi,score", [("30", -100), ("15", -50), ("0", 0)])
def test_negative_momentum_exhaustion_is_symmetric(rsi: str, score: int) -> None:
    result = assess(MomentumContinuation(), features(momentum=dict(roc_percent="-2", rsi=rsi, close_change="-1"),
        volume=dict(relative_volume="1", taker_buy_ratio="0.2")))
    assert result.score == score


def test_contradictory_momentum_evidence_reduces_confidence() -> None:
    result = assess(MomentumContinuation(), features(momentum=dict(roc_percent="2", rsi="30", close_change="1"),
        volume=dict(relative_volume="1", taker_buy_ratio="0.2")))
    assert result.score == 20  # 40 - 25 + 20 - 15.
    assert result.confidence == Decimal("0.04")
    assert result.direction == "NEUTRAL"


def test_contradictory_reversion_evidence_offsets_instead_of_reinforcing() -> None:
    result = assess(MeanReversion(), features(trend=dict(distance_from_slow="0.03", distance_from_fast="0.02"),
        momentum=dict(rsi="30"), regime=dict(directional_efficiency="0.25")))
    assert result.score == -20  # -60 + 40.
    assert result.confidence == Decimal("0.04") and result.direction == "NEUTRAL"


@pytest.mark.parametrize("relative,score", [("1", -100), ("2", -50), ("3", 0), ("1e1000000", 0)])
def test_relative_volume_suppresses_reversion(relative: str, score: int) -> None:
    snapshot = positive_stretch()
    group = snapshot.regime.model_copy(update={"values": snapshot.regime.values.model_copy(update={"relative_volume": Decimal(relative)})})
    assert assess(MeanReversion(), snapshot.model_copy(update={"regime": group})).score == score


@pytest.mark.parametrize("change", ["missing", "duplicate", "missing_generation", "missing_close", "warmup"])
def test_incomplete_provenance_or_history_never_scores(change: str) -> None:
    snapshot = positive_trend()
    if change == "missing":
        snapshot = snapshot.model_copy(update={"sources": snapshot.sources[1:]})
    elif change == "duplicate":
        snapshot = snapshot.model_copy(update={"sources": (*snapshot.sources, snapshot.sources[0])})
    elif change == "missing_generation":
        snapshot = snapshot.model_copy(update={"sources": (snapshot.sources[0].model_copy(update={"generation": None}), *snapshot.sources[1:])})
    elif change == "missing_close":
        snapshot = snapshot.model_copy(update={"closed_candle_time": None})
    else:
        snapshot = snapshot.model_copy(update={"closed_candles": 49})
    result = assess(TrendFollowing(), snapshot)
    assert result.readiness in ("unavailable", "warming_up") and result.score is None
