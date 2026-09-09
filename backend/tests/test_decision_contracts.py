from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.application.decision_identity import decision_identity, policy_identity
from src.application.decision_settings import DecisionSettings
from src.domain.decisions import DecisionOutcome, DecisionPolicy, DecisionReason, DecisionRecord
from strategy_fixtures import NOW


def record(**updates) -> DecisionRecord:
    fields = dict(decision_id="decision_test", symbol="BTCUSDT", generated_at=NOW,
        source_strategy_timestamp=NOW, source_feature_timestamp=NOW, strategy_snapshot_id="features_test",
        observation_id="observation_test", strategy_settings_id="settings_test", strategy_engine_version="strategy-engine-v1",
        candidate_id="candidate_test", direction="LONG", outcome="ELIGIBLE", readiness="ready",
        composite_score="80", confidence="0.8", agreement="1", contributing_strategies=("trend_following", "momentum_continuation"),
        incomplete_strategy_coverage=False, reasons=({"code": "eligibility_checks_passed"},),
        policy_id="policy_test", engine_version="decision-engine-v1")
    return DecisionRecord(**(fields | updates))


def test_immutable_record_and_reason_have_deterministic_serialization() -> None:
    value = record()
    assert DecisionRecord.model_validate_json(value.model_dump_json()) == value
    assert value.model_dump_json() == record().model_dump_json()
    with pytest.raises(ValidationError):
        value.outcome = DecisionOutcome.BLOCKED
    with pytest.raises(ValidationError):
        value.reasons[0].code = "no_candidate"


@pytest.mark.parametrize("field", ["quantity", "leverage", "price", "order_type", "stop_loss", "take_profit", "execution_mode", "api_key"])
def test_no_executable_fields_are_accepted(field: str) -> None:
    assert field not in DecisionRecord.model_fields
    with pytest.raises(ValidationError):
        record(**{field: 1})


@pytest.mark.parametrize("field", ["composite_score", "confidence", "agreement"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, 101, -101])
def test_record_rejects_nonfinite_and_out_of_range_values(field, value) -> None:
    with pytest.raises(ValidationError):
        record(**{field: value})


@pytest.mark.parametrize("updates", [
    {"readiness": "stale"}, {"candidate_id": None}, {"direction": "NEUTRAL"},
    {"confidence": 0}, {"agreement": 0}, {"composite_score": -80},
    {"contributing_strategies": ()}, {"contributing_strategies": ("trend_following", "trend_following")},
    {"reasons": ()}, {"reasons": ({"code": "no_candidate"},)},
    {"reasons": ({"code": "eligibility_checks_passed"}, {"code": "eligibility_checks_passed"})},
    {"incomplete_strategy_coverage": True}, {"generated_at": NOW.replace(tzinfo=None)},
    {"generated_at": NOW - timedelta(seconds=1)}, {"source_feature_timestamp": NOW + timedelta(seconds=1)},
    {"source_strategy_timestamp": None}, {"symbol": "btcusdt"}, {"symbol": " BTCUSDT "},
])
def test_impossible_eligible_records_are_rejected(updates) -> None:
    with pytest.raises(ValidationError):
        record(**updates)


def test_no_action_nulls_candidate_values_but_preserves_available_agreement() -> None:
    value = record(outcome="NO_ACTION", candidate_id=None, direction="NEUTRAL", composite_score=None,
                   confidence=None, contributing_strategies=(), reasons=({"code": "no_candidate"},))
    assert value.agreement == 1 and value.confidence is None
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(value.model_copy(update={"readiness": "stale"}))


def test_blocked_record_can_preserve_valid_candidate_or_omit_invalid_data() -> None:
    blocked = record(outcome="BLOCKED", readiness="stale", generated_at=NOW - timedelta(seconds=1),
                     reasons=({"code": "future_timestamp"},))
    assert blocked.candidate_id == "candidate_test" and blocked.confidence == Decimal("0.8")
    invalid = record(outcome="BLOCKED", readiness="unavailable", source_strategy_timestamp=None,
        source_feature_timestamp=None, candidate_id=None, direction="NEUTRAL", composite_score=None,
        confidence=None, agreement=None, contributing_strategies=(), reasons=({"code": "invalid_strategy_snapshot"},))
    assert "NaN" not in invalid.model_dump_json()


@pytest.mark.parametrize("reason", ["no_candidate", "incomplete_strategy_coverage"])
def test_blocked_record_requires_a_blocking_reason(reason) -> None:
    with pytest.raises(ValidationError, match="blocking reason"):
        record(outcome="BLOCKED", candidate_id=None, direction="NEUTRAL", composite_score=None,
            confidence=None, contributing_strategies=(), reasons=({"code": reason},),
            incomplete_strategy_coverage=reason == "incomplete_strategy_coverage")


def test_coverage_flag_cannot_contradict_preserved_reason() -> None:
    with pytest.raises(ValidationError, match="coverage provenance"):
        record(reasons=({"code": "eligibility_checks_passed"}, {"code": "incomplete_strategy_coverage"}),
               incomplete_strategy_coverage=False)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True])
def test_reason_context_is_finite(value) -> None:
    with pytest.raises(ValidationError):
        DecisionReason(code="insufficient_agreement", observed=value)


def test_exact_policy_defaults_and_domain_projection() -> None:
    settings = DecisionSettings()
    assert settings.max_strategy_snapshot_age_seconds == 10
    assert settings.min_decision_agreement == Decimal("0.50")
    assert settings.min_contributing_strategies == 2
    assert settings.block_incomplete_strategy_coverage is False
    assert DecisionPolicy.model_validate(settings).model_dump() == settings.model_dump()
    with pytest.raises(ValidationError):
        settings.min_contributing_strategies = 1


@pytest.mark.parametrize("field,value", [
    ("max_strategy_snapshot_age_seconds", 0), ("max_strategy_snapshot_age_seconds", -1),
    ("max_strategy_snapshot_age_seconds", "NaN"), ("max_strategy_snapshot_age_seconds", "Infinity"),
    ("max_strategy_snapshot_age_seconds", True), ("min_decision_agreement", "-0.01"),
    ("min_decision_agreement", "1.01"), ("min_decision_agreement", "NaN"),
    ("min_decision_agreement", "Infinity"), ("min_decision_agreement", True),
    ("min_contributing_strategies", 0), ("min_contributing_strategies", 4),
    ("min_contributing_strategies", True), ("min_contributing_strategies", 1.5),
    ("min_contributing_strategies", "2.0"), ("block_incomplete_strategy_coverage", 1),
    ("block_incomplete_strategy_coverage", "unexpected"), ("unknown_gate", 1),
])
def test_invalid_settings_are_rejected(field, value) -> None:
    with pytest.raises(ValidationError):
        DecisionSettings(**{field: value})


@pytest.mark.parametrize("agreement", ["0", "0.5", "1"])
@pytest.mark.parametrize("count", [1, 2, 3])
def test_policy_threshold_boundaries(agreement, count) -> None:
    value = DecisionSettings(min_decision_agreement=agreement, min_contributing_strategies=count)
    assert value.min_decision_agreement == Decimal(agreement)
    assert value.min_contributing_strategies == count


def test_settings_load_typed_process_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DECISION_MIN_CONTRIBUTING_STRATEGIES", "3")
    monkeypatch.setenv("DECISION_BLOCK_INCOMPLETE_STRATEGY_COVERAGE", "true")
    monkeypatch.setenv("DECISION_MIN_DECISION_AGREEMENT", "0.6")
    value = DecisionSettings()
    assert value.min_contributing_strategies == 3
    assert value.block_incomplete_strategy_coverage is True
    assert value.min_decision_agreement == Decimal("0.6")


def test_stable_policy_and_decision_identities_cover_material_inputs() -> None:
    policy = policy_identity(DecisionSettings(), ("ETHUSDT", "BTCUSDT"))
    assert policy == policy_identity(DecisionSettings(min_decision_agreement="0.500"), ("BTCUSDT", "ETHUSDT"))
    assert policy != policy_identity(DecisionSettings(min_contributing_strategies=1), ("BTCUSDT", "ETHUSDT"))
    fields = dict(policy_id=policy, symbol="BTCUSDT", observation_id="observation_test", candidate_id="candidate_test",
                  outcome=DecisionOutcome.ELIGIBLE, strategy_settings_id="settings_test", strategy_engine_version="strategy-engine-v1")
    expected = decision_identity(**fields)
    assert expected == decision_identity(**fields)
    for name, value in (("policy_id", "other_policy"), ("observation_id", "other_observation"),
                        ("candidate_id", None), ("outcome", DecisionOutcome.BLOCKED),
                        ("symbol", "ETHUSDT"), ("strategy_settings_id", "other_settings"),
                        ("strategy_engine_version", "strategy-engine-v2")):
        assert decision_identity(**(fields | {name: value})) != expected
