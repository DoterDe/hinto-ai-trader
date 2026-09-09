from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from src.application.decision_engine import DecisionEngine, DecisionSourceError
from src.application.decision_settings import DecisionSettings
from src.domain.decisions import DecisionRecord
from decision_fixtures import strategy_snapshot
from strategy_fixtures import NOW


def codes(record):
    return tuple(reason.code.value for reason in record.reasons)


@pytest.mark.parametrize("direction", [1, -1])
def test_ready_candidate_is_eligible_with_source_values_preserved(direction) -> None:
    source = strategy_snapshot(direction=direction)
    result = DecisionEngine().evaluate(source, now=NOW)
    assert result.outcome == "ELIGIBLE" and result.readiness == "ready"
    assert result.candidate_id == source.candidate.candidate_id
    assert result.composite_score == source.composite_score == 90 * direction
    assert result.confidence == source.confidence == Decimal("0.9")
    assert result.agreement == source.agreement
    assert result.contributing_strategies == source.candidate.contributing_strategies
    assert codes(result) == ("eligibility_checks_passed",)
    assert DecisionRecord.model_validate_json(result.model_dump_json()) == result


def test_valid_no_candidate_is_no_action_not_blocked() -> None:
    result = DecisionEngine().evaluate(strategy_snapshot(candidate=False), now=NOW)
    assert result.outcome == "NO_ACTION" and result.readiness == "ready"
    assert result.candidate_id is result.composite_score is result.confidence is None
    assert result.direction == "NEUTRAL" and result.agreement == 1
    assert codes(result) == ("no_candidate",)


@pytest.mark.parametrize("microseconds,outcome", [(0, "ELIGIBLE"), (9_999_999, "ELIGIBLE"), (10_000_000, "BLOCKED"), (10_000_001, "BLOCKED")])
def test_age_limit_is_strict_and_microsecond_exact(microseconds, outcome) -> None:
    result = DecisionEngine().evaluate(strategy_snapshot(), now=NOW + timedelta(microseconds=microseconds))
    assert result.outcome == outcome
    if outcome == "BLOCKED":
        assert result.readiness == "stale"
        assert codes(result) == ("snapshot_too_old", "feature_too_old")
        assert result.candidate_id is not None


def test_future_and_expired_no_candidate_snapshots_are_blocked() -> None:
    for source in (strategy_snapshot(), strategy_snapshot(candidate=False)):
        future = DecisionEngine().evaluate(source, now=NOW - timedelta(microseconds=1))
        assert future.outcome == "BLOCKED" and future.readiness == "stale"
        assert codes(future) == ("future_timestamp",)
    expired = DecisionEngine().evaluate(strategy_snapshot(candidate=False), now=NOW + timedelta(seconds=10))
    assert expired.outcome == "BLOCKED" and expired.candidate_id is None


@pytest.mark.parametrize("agreement,outcome", [("0.499999", "BLOCKED"), ("0.50", "ELIGIBLE"), ("1", "ELIGIBLE")])
def test_agreement_gate_uses_existing_value_at_inclusive_threshold(agreement, outcome) -> None:
    result = DecisionEngine().evaluate(strategy_snapshot(agreement=agreement), now=NOW)
    assert result.outcome == outcome and result.agreement == Decimal(agreement)
    if outcome == "BLOCKED":
        assert result.readiness == "ready"
        reason = result.reasons[0]
        assert reason.code == "insufficient_agreement"
        assert reason.observed == Decimal(agreement) and reason.threshold == Decimal("0.5")


@pytest.mark.parametrize("count,outcome", [(1, "BLOCKED"), (2, "ELIGIBLE"), (3, "ELIGIBLE")])
def test_contributor_count_threshold(count, outcome) -> None:
    result = DecisionEngine().evaluate(strategy_snapshot(count=count), now=NOW)
    assert result.outcome == outcome
    assert len(result.contributing_strategies) == count
    if count == 1:
        assert codes(result) == ("insufficient_contributors",)
        assert result.reasons[0].threshold == 2


@pytest.mark.parametrize("block,outcome", [(False, "ELIGIBLE"), (True, "BLOCKED")])
def test_incomplete_coverage_is_explicit_and_configurable(block, outcome) -> None:
    engine = DecisionEngine(settings=DecisionSettings(block_incomplete_strategy_coverage=block))
    result = engine.evaluate(strategy_snapshot(incomplete=True), now=NOW)
    assert result.outcome == outcome and result.incomplete_strategy_coverage is True
    assert "incomplete_strategy_coverage" in codes(result)
    assert ("incomplete_coverage_blocked" in codes(result)) is block


def test_all_policy_failures_are_reported_in_stable_order() -> None:
    source = strategy_snapshot(count=1, agreement="0.4", incomplete=True)
    result = DecisionEngine(settings=DecisionSettings(block_incomplete_strategy_coverage=True)).evaluate(source, now=NOW)
    assert codes(result) == ("incomplete_strategy_coverage", "insufficient_agreement", "insufficient_contributors", "incomplete_coverage_blocked")


def test_explicit_time_is_required_and_naive_time_is_programmer_error() -> None:
    with pytest.raises(TypeError):
        DecisionEngine().evaluate(strategy_snapshot())
    for value in (NOW.replace(tzinfo=None), "2026-09-09", None):
        with pytest.raises(ValueError, match="timezone-aware"):
            DecisionEngine().evaluate(strategy_snapshot(), now=value)


def test_unsafe_identifiers_and_non_models_raise_without_raw_input_text() -> None:
    with pytest.raises(TypeError):
        DecisionEngine().evaluate({}, now=NOW)
    bad = strategy_snapshot().model_copy(update={"observation_id": ""})
    with pytest.raises(ValueError, match="safe decision record"):
        DecisionEngine().evaluate(bad, now=NOW)


def test_repeated_observation_keeps_identity_across_evaluation_time() -> None:
    source = strategy_snapshot()
    engine = DecisionEngine()
    first = engine.evaluate(source, now=NOW)
    assert first == engine.evaluate(source, now=NOW)
    later = engine.evaluate(source, now=NOW + timedelta(seconds=1))
    assert later.generated_at != first.generated_at
    assert later.decision_id == first.decision_id
    expired = engine.evaluate(source, now=NOW + timedelta(seconds=10))
    assert expired.decision_id != first.decision_id


def test_policy_changes_identity_without_changing_source_scores() -> None:
    source = strategy_snapshot()
    first = DecisionEngine().evaluate(source, now=NOW)
    second = DecisionEngine(settings=DecisionSettings(min_decision_agreement="0.6")).evaluate(source, now=NOW)
    assert first.outcome == second.outcome == "ELIGIBLE"
    assert first.policy_id != second.policy_id and first.decision_id != second.decision_id
    assert first.composite_score == second.composite_score


def test_pure_evaluation_ignores_clock_and_preserves_input_and_decimal_context() -> None:
    def forbidden_clock():
        pytest.fail("pure evaluation must not read wall clock")
    engine = DecisionEngine(clock=forbidden_clock)
    source = strategy_snapshot()
    original = source.model_dump_json()
    first = engine.evaluate(source, now=NOW)
    with localcontext() as ctx:
        ctx.prec = 2
        assert first == engine.evaluate(source, now=NOW)
    assert source.model_dump_json() == original


def test_allowlist_blocks_unsupported_symbols_without_mutating_them() -> None:
    result = DecisionEngine(symbols=("ETHUSDT",)).evaluate(strategy_snapshot(), now=NOW)
    assert result.outcome == "BLOCKED" and result.symbol == "BTCUSDT"
    assert codes(result) == ("unsupported_symbol",)


class Provider:
    def __init__(self):
        self.calls = []
        self.values = {"BTCUSDT": strategy_snapshot(), "ETHUSDT": strategy_snapshot(symbol="ETHUSDT", candidate=False)}
    def latest(self, symbol):
        self.calls.append(symbol)
        return self.values[symbol]


def test_latest_and_status_are_on_demand_and_isolate_symbols() -> None:
    provider = Provider()
    engine = DecisionEngine(provider, symbols=tuple(provider.values), clock=lambda: NOW)
    btc, eth = engine.latest("BTCUSDT"), engine.latest("ETHUSDT")
    assert btc.outcome == "ELIGIBLE" and eth.outcome == "NO_ACTION"
    assert btc.decision_id != eth.decision_id
    assert provider.calls == ["BTCUSDT", "ETHUSDT"]
    status = engine.status()
    assert status.evaluation_mode == "on_demand" and len(status.symbols) == 2
    assert status.policy.min_contributing_strategies == 2
    with pytest.raises(KeyError):
        engine.latest("UNKNOWN")
    assert "UNKNOWN" not in provider.calls


def test_provider_mismatch_or_failure_does_not_return_another_symbols_record() -> None:
    provider = Provider()
    provider.values["BTCUSDT"] = provider.values["ETHUSDT"]
    engine = DecisionEngine(provider, symbols=("BTCUSDT",), clock=lambda: NOW)
    with pytest.raises(DecisionSourceError):
        engine.latest("BTCUSDT")
    with pytest.raises(DecisionSourceError):
        DecisionEngine(symbols=("BTCUSDT",)).latest("BTCUSDT")
