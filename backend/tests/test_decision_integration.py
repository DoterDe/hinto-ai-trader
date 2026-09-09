import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.application.decision_engine import DecisionEngine, DecisionSourceError
from src.application.decision_settings import DecisionSettings
from src.application.strategy_engine import StrategyEngine
from src.application.strategy_settings import StrategySettings
from src.domain.features import Readiness
from src.domain.strategies import StrategyId
from decision_fixtures import strategy_snapshot
from strategy_fixtures import NOW, features, state
from test_decision_engine import codes


def aligned_features(direction=1):
    return features(
        trend=dict(ema_fast="102" if direction > 0 else "98", ema_slow="101" if direction > 0 else "99",
                   ema_long="100", distance_from_slow="0.02" if direction > 0 else "-0.02"),
        momentum=dict(rsi="70" if direction > 0 else "30", roc_percent=str(2 * direction), close_change=str(direction)),
        volume=dict(relative_volume="1", taker_buy_ratio="0.8" if direction > 0 else "0.2"),
        regime=dict(directional_efficiency="0.55"))


@pytest.mark.parametrize("direction", [1, -1])
def test_actual_strategy_consensus_is_eligible_and_unchanged(direction) -> None:
    source = StrategyEngine().evaluate(aligned_features(direction))
    before = source.model_dump_json()
    assert source.candidate is not None
    result = DecisionEngine().evaluate(source, now=NOW)
    assert result.outcome == "ELIGIBLE"
    assert result.contributing_strategies == (StrategyId.TREND, StrategyId.MOMENTUM)
    assert result.composite_score == source.composite_score
    assert result.confidence == source.confidence
    assert source.model_dump_json() == before


def test_actual_neutral_source_is_no_action() -> None:
    source = StrategyEngine().evaluate(features())
    assert source.candidate is None and source.composite_score == 0
    assert DecisionEngine().evaluate(source, now=NOW).outcome == "NO_ACTION"


@pytest.mark.parametrize("readiness,outcome,code", [
    (Readiness.STALE, "BLOCKED", "source_stale"),
    (Readiness.WARMING_UP, "NO_ACTION", "source_warming_up"),
    (Readiness.UNAVAILABLE, "NO_ACTION", "source_unavailable"),
])
def test_actual_unready_strategy_without_candidate_has_explicit_outcome(readiness, outcome, code) -> None:
    source = StrategyEngine().evaluate(state(aligned_features(), "momentum", readiness))
    result = DecisionEngine().evaluate(source, now=NOW)
    assert result.outcome == outcome and result.candidate_id is None
    assert code in codes(result)


def test_single_family_policy_is_independent_of_strategy_thresholds() -> None:
    source = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.TREND,))).evaluate(aligned_features())
    assert source.candidate is not None and source.composite_score == 100
    assert DecisionEngine().evaluate(source, now=NOW).outcome == "BLOCKED"
    assert DecisionEngine(settings=DecisionSettings(min_contributing_strategies=1)).evaluate(source, now=NOW).outcome == "ELIGIBLE"


def test_actual_partial_coverage_preserves_provenance_and_gate() -> None:
    config = StrategySettings(momentum_weight=4)
    source = StrategyEngine(settings=config).evaluate(state(aligned_features(), "trend", Readiness.UNAVAILABLE))
    assert source.candidate is not None and "incomplete_strategy_coverage" in source.reasons
    allow = DecisionSettings(min_contributing_strategies=1)
    result = DecisionEngine(settings=allow).evaluate(source, now=NOW)
    assert result.outcome == "ELIGIBLE" and result.incomplete_strategy_coverage
    strict = DecisionSettings(min_contributing_strategies=1, block_incomplete_strategy_coverage=True)
    assert DecisionEngine(settings=strict).evaluate(source, now=NOW).outcome == "BLOCKED"


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", "different_snapshot"), ("observation_id", "different_observation"),
    ("symbol", "ETHUSDT"), ("direction", "SHORT"), ("direction", "NEUTRAL"),
    ("composite_score", Decimal(20)), ("confidence", Decimal("0.2")),
    ("confidence", Decimal("NaN")), ("confidence", Decimal("Infinity")),
    ("composite_score", Decimal(101)), ("contributing_strategies", (StrategyId.TREND, StrategyId.TREND)),
    ("generated_at", NOW.replace(tzinfo=None)),
])
def test_malformed_candidate_copies_return_safe_blocked_records(field, value) -> None:
    source = strategy_snapshot()
    bad = source.model_copy(update={"candidate": source.candidate.model_copy(update={field: value})})
    result = DecisionEngine().evaluate(bad, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "unavailable"
    assert result.candidate_id is result.composite_score is result.confidence is None
    assert result.direction == "NEUTRAL"
    assert codes(result) == ("invalid_strategy_snapshot",)
    assert "NaN" not in result.model_dump_json() and "Infinity" not in result.model_dump_json()


@pytest.mark.parametrize("field,value", [
    ("candidate_id", "wrong_candidate_hash"), ("generated_at", NOW - timedelta(seconds=1)),
    ("contributing_strategies", (StrategyId.TREND, StrategyId.MEAN_REVERSION)),
    ("contributing_strategies", (StrategyId.TREND,)), ("reasons", ()),
])
def test_semantically_inconsistent_but_typed_candidates_are_blocked(field, value) -> None:
    source = strategy_snapshot()
    bad = source.model_copy(update={"candidate": source.candidate.model_copy(update={field: value})})
    result = DecisionEngine().evaluate(bad, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "unavailable"
    assert result.candidate_id is None


def test_future_candidate_timestamp_is_stale_even_when_it_mismatches_snapshot() -> None:
    source = strategy_snapshot()
    bad = source.model_copy(update={"candidate": source.candidate.model_copy(update={"generated_at": NOW + timedelta(seconds=1)})})
    result = DecisionEngine().evaluate(bad, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "stale"
    assert "future_timestamp" in codes(result) and "timestamp_mismatch" in codes(result)


@pytest.mark.parametrize("field,value", [
    ("agreement", Decimal("NaN")), ("agreement", Decimal("Infinity")), ("agreement", Decimal("1.01")),
    ("confidence", Decimal("-0.1")), ("composite_score", Decimal("-101")),
    ("source_feature_timestamp", NOW.replace(tzinfo=None)), ("generated_at", NOW.replace(tzinfo=None)),
    ("assessments", ()),
])
def test_invalid_snapshot_copies_fail_closed_without_serialization_errors(field, value) -> None:
    bad = strategy_snapshot().model_copy(update={field: value})
    result = DecisionEngine().evaluate(bad, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "unavailable"
    assert result.candidate_id is None
    assert "NaN" not in result.model_dump_json() and "Infinity" not in result.model_dump_json()


def test_model_coercion_cannot_make_raw_numeric_source_times_eligible() -> None:
    source = strategy_snapshot()
    epoch = int(NOW.timestamp())
    raw = source.model_copy(update={"generated_at": epoch, "source_feature_timestamp": epoch})
    result = DecisionEngine().evaluate(raw, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "unavailable"
    assert result.source_strategy_timestamp is result.source_feature_timestamp is None


def test_fresh_strategy_timestamp_does_not_freshen_old_feature_timestamp() -> None:
    source = strategy_snapshot()
    older = NOW - timedelta(seconds=10)
    changed = source.model_copy(update={"source_feature_timestamp": older,
        "assessments": tuple(item.model_copy(update={"source_feature_timestamp": older}) for item in source.assessments)})
    result = DecisionEngine().evaluate(changed, now=NOW)
    assert result.outcome == "BLOCKED" and result.readiness == "stale"
    assert codes(result) == ("feature_too_old",)


def test_incomplete_coverage_cannot_be_hidden_by_removing_reason() -> None:
    source = strategy_snapshot(incomplete=True)
    reasons = ("candidate_thresholds_met",)
    changed = source.model_copy(update={"reasons": reasons,
        "candidate": source.candidate.model_copy(update={"reasons": reasons})})
    result = DecisionEngine().evaluate(changed, now=NOW)
    assert result.outcome == "BLOCKED" and "invalid_candidate_provenance" in codes(result)


def test_phase4_threshold_failure_provenance_cannot_be_overridden_by_candidate() -> None:
    source = strategy_snapshot()
    changed = source.model_copy(update={"reasons": (*source.reasons, "below_candidate_confidence")})
    assert DecisionEngine().evaluate(changed, now=NOW).outcome == "BLOCKED"


def test_actual_later_read_keeps_decision_identity_and_changed_observation_does_not() -> None:
    features_now = aligned_features()
    strategies, decisions = StrategyEngine(), DecisionEngine()
    first_source = strategies.evaluate(features_now)
    first = decisions.evaluate(first_source, now=NOW)
    later_time = NOW + timedelta(seconds=1)
    later_source = strategies.evaluate(features_now.model_copy(update={"generated_at": later_time}))
    later = decisions.evaluate(later_source, now=later_time)
    assert first_source.snapshot_id != later_source.snapshot_id
    assert first.decision_id == later.decision_id
    changed_source = strategies.evaluate(features_now.model_copy(update={"closed_candle_time": NOW - timedelta(seconds=1)}))
    changed = decisions.evaluate(changed_source, now=NOW)
    assert changed.observation_id != first.observation_id
    assert changed.decision_id != first.decision_id


def test_changed_upstream_settings_change_decision_identity() -> None:
    features_now = aligned_features()
    first = DecisionEngine().evaluate(StrategyEngine().evaluate(features_now), now=NOW)
    changed = DecisionEngine().evaluate(StrategyEngine(settings=StrategySettings(trend_weight=2)).evaluate(features_now), now=NOW)
    assert changed.outcome == first.outcome == "ELIGIBLE"
    assert first.decision_id != changed.decision_id


def test_bad_provider_response_and_errors_are_sanitized() -> None:
    class Provider:
        def latest(self, symbol):
            raise RuntimeError("sensitive-provider-error-marker")
    engine = DecisionEngine(Provider(), symbols=("BTCUSDT",), clock=lambda: NOW)
    with pytest.raises(DecisionSourceError) as error:
        engine.latest("BTCUSDT")
    assert "sensitive-provider-error-marker" not in str(error.value)


def test_decision_core_has_no_execution_feature_or_network_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    files = [root / "domain" / "decisions.py", *sorted((root / "application").glob("decision_*.py"))]
    forbidden_names = {"TradeIntent", "ApprovedTradeIntent", "RiskEngine", "PaperExecutionGateway", "ExecutionGateway"}
    forbidden_modules = ("src.infrastructure", "src.application.feature_engine", "src.application.market_data_hub",
                         "src.application.risk_engine", "src.domain.execution", "openai", "redis", "sqlite3", "httpx", "websockets")
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden_names)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(name == forbidden or name.startswith(forbidden + ".") for name in names for forbidden in forbidden_modules)


def test_eligible_record_cannot_include_blocking_reason() -> None:
    result = DecisionEngine().evaluate(strategy_snapshot(), now=NOW)
    bad = result.model_dump()
    bad["reasons"] = (*bad["reasons"], {"code": "insufficient_contributors"})
    with pytest.raises(ValidationError):
        type(result).model_validate(bad)
