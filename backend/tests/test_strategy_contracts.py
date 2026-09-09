from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.application.strategy_settings import StrategySettings
from src.domain.strategies import (
    StrategyAssessment, StrategyCandidate, StrategyDirection, StrategyEvidence,
    StrategyId, StrategyReadiness,
)

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def assessment(**updates: object) -> StrategyAssessment:
    fields = dict(strategy_id=StrategyId.TREND, symbol="BTCUSDT", generated_at=NOW,
                  source_feature_timestamp=NOW, snapshot_id="features_test", direction="LONG",
                  score=50, confidence="0.5", readiness="ready", reasons=(),
                  required_feature_groups=("trend",), evidence=(StrategyEvidence(
                      name="ema", value="0.005", normalized="0.5", weight=100,
                      contribution=50, code="signed_ramp"),))
    return StrategyAssessment(**(fields | updates))


def candidate(**updates: object) -> StrategyCandidate:
    return StrategyCandidate(**(dict(candidate_id="candidate_test", symbol="BTCUSDT", generated_at=NOW,
        snapshot_id="features_test", observation_id="observations_test", direction="LONG",
        composite_score=50, confidence="0.6", contributing_strategies=(StrategyId.TREND,),
        reasons=("consensus_thresholds_met",)) | updates))


def test_assessments_are_immutable_explainable_and_round_trip() -> None:
    result = assessment()
    assert result.evidence[0].contribution == Decimal(50)
    assert StrategyAssessment.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        result.score = Decimal(20)
    with pytest.raises(ValidationError):
        result.evidence[0].value = Decimal(0)


@pytest.mark.parametrize("field", ["score", "confidence"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, 101, -101])
def test_assessment_numeric_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        assessment(**{field: value})


@pytest.mark.parametrize("value", ["-0.01", "1.01"])
def test_confidence_is_a_fraction(value: str) -> None:
    with pytest.raises(ValidationError):
        candidate(confidence=value)


@pytest.mark.parametrize("score,direction", [(100, "LONG"), (-100, "SHORT"), (0, "NEUTRAL")])
def test_exact_score_bounds_and_neutral(score: int, direction: str) -> None:
    evidence = StrategyEvidence(name="boundary", value=score, normalized=Decimal(score) / 100,
                                weight=100, contribution=score, code="boundary")
    assert assessment(score=score, direction=direction, evidence=(evidence,)).score == score


def test_score_cannot_hide_unexplained_contributions() -> None:
    with pytest.raises(ValidationError):
        assessment(score=49)
    with pytest.raises(ValidationError):
        StrategyEvidence(name="bad", value=1, weight=20, normalized=1, contribution=100, code="bad")


@pytest.mark.parametrize("state", ["stale", "unavailable", "warming_up"])
def test_unready_assessments_have_no_numeric_score_or_direction(state: str) -> None:
    result = assessment(readiness=state, direction="NEUTRAL", score=None, confidence=None,
                        reasons=("trend:missing",), evidence=())
    assert result.score is result.confidence is None
    assert result.readiness.value == state
    with pytest.raises(ValidationError):
        assessment(readiness=state)


@pytest.mark.parametrize("field,value", [("direction", "NEUTRAL"), ("composite_score", -50),
    ("composite_score", 0), ("contributing_strategies", ()), ("contributing_strategies", ("trend_following", "trend_following"))])
def test_candidates_require_coherent_analytical_direction(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        candidate(**{field: value})


@pytest.mark.parametrize("field", ["quantity", "leverage", "order_type", "execution_mode"])
def test_candidate_has_no_executable_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        candidate(**{field: 1})


def test_candidate_deterministic_serialization_and_aware_timestamp() -> None:
    assert candidate().model_dump_json() == candidate().model_dump_json()
    with pytest.raises(ValidationError):
        candidate(generated_at=NOW.replace(tzinfo=None))


def test_engineering_defaults_match_task() -> None:
    config = StrategySettings()
    assert config.enabled_strategies == tuple(StrategyId)
    assert (config.min_absolute_strategy_score, config.candidate_score_threshold,
            config.min_candidate_confidence) == (25, 40, Decimal("0.55"))
    assert (config.rsi_extreme_low, config.rsi_neutral_low, config.rsi_neutral_high,
            config.rsi_extreme_high) == (30, 45, 55, 70)
    assert config.max_acceptable_spread_bps == 15
    assert config.trend_efficiency_floor == Decimal("0.25")
    assert config.strong_trend_efficiency == Decimal("0.55")
    assert config.relative_volume_baseline == 1
    assert all(config.weight(item) == 1 for item in StrategyId)


@pytest.mark.parametrize("field", [name for name in StrategySettings.model_fields if name != "enabled_strategies"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", True])
def test_settings_require_finite_numeric_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        StrategySettings(**{field: value})


@pytest.mark.parametrize("updates", [
    {"candidate_score_threshold": 24}, {"min_candidate_confidence": 0},
    {"min_candidate_confidence": "1.01"}, {"min_absolute_strategy_score": 101},
    {"rsi_extreme_low": 0}, {"rsi_extreme_high": 100}, {"rsi_neutral_low": 55},
    {"trend_efficiency_floor": "0.55"}, {"strong_trend_efficiency": "1.01"},
    {"relative_volume_exhaustion": 1}, {"ema_separation_saturation": "0.0005"},
    {"price_distance_dead_zone": "0.01"}, {"roc_saturation": "0.1"},
    {"taker_bias_saturation": "0.1"}, {"reversion_stretch_saturation": 1},
    {"atr_hard_limit": "0.025"}, {"optional_context_missing_quality": -1},
    {"max_feature_age_seconds": 0}, {"trend_weight": 0}, {"momentum_weight": 101},
    {"enabled_strategies": ()}, {"enabled_strategies": ("trend_following", "trend_following")},
    {"enabled_strategies": ("unknown",)},
])
def test_incoherent_settings_are_rejected(updates: dict) -> None:
    with pytest.raises(ValidationError):
        StrategySettings(**updates)


def test_settings_environment_and_frozen_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATEGY_CANDIDATE_SCORE_THRESHOLD", "45")
    monkeypatch.setenv("STRATEGY_ENABLED_STRATEGIES", '["trend_following"]')
    config = StrategySettings()
    assert config.candidate_score_threshold == 45
    assert config.enabled_strategies == (StrategyId.TREND,)
    with pytest.raises(ValidationError):
        config.trend_weight = Decimal(2)
