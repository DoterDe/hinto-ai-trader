from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.application.risk_engine import RiskEngine, RiskLimits
from src.domain.models import SignalSide, TradeIntent


def make_intent(**overrides: object) -> TradeIntent:
    data = {
        "signal_id": "sig-1",
        "symbol": "BTCUSDT",
        "side": SignalSide.LONG,
        "quantity": 0.1,
        "created_at": datetime.now(timezone.utc),
    }
    data.update(overrides)
    return TradeIntent(**data)


def test_approves_valid_intent() -> None:
    engine = RiskEngine(RiskLimits(max_quantity=1.0))
    decision = engine.evaluate(make_intent())
    assert decision.approved is True
    assert decision.approved_intent is not None


def test_rejects_duplicate_signal() -> None:
    engine = RiskEngine()
    intent = make_intent()
    assert engine.evaluate(intent).approved is True
    second = engine.evaluate(intent)
    assert second.approved is False
    assert second.reason == "duplicate_signal"


def test_rejects_stale_signal() -> None:
    engine = RiskEngine(RiskLimits(max_signal_age_seconds=30))
    old = datetime.now(timezone.utc) - timedelta(seconds=31)
    decision = engine.evaluate(make_intent(created_at=old))
    assert decision.approved is False
    assert decision.reason == "stale_or_future_signal"


def test_rejects_quantity_over_limit() -> None:
    engine = RiskEngine(RiskLimits(max_quantity=0.5))
    decision = engine.evaluate(make_intent(quantity=0.6))
    assert decision.approved is False
    assert decision.reason == "quantity_limit_exceeded"


def test_can_disable_execution() -> None:
    engine = RiskEngine(RiskLimits(execution_enabled=False))
    decision = engine.evaluate(make_intent())
    assert decision.approved is False
    assert decision.reason == "execution_disabled"


@pytest.mark.parametrize(
    "age_seconds, approved", [(0, True), (30, True), (30.001, False), (-0.001, False)]
)
def test_signal_age_boundaries(age_seconds: float, approved: bool) -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = RiskEngine().evaluate(
        make_intent(created_at=now - timedelta(seconds=age_seconds)), now=now
    )
    assert decision.approved is approved
    if approved:
        assert decision.approved_intent is not None
        assert decision.approved_intent.approved_at == now
    else:
        assert decision.reason == "stale_or_future_signal"


def test_timezone_offsets_represent_the_same_instant() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    local = now.astimezone(timezone(timedelta(hours=5)))
    assert RiskEngine().evaluate(make_intent(created_at=local), now=now).approved


@pytest.mark.parametrize(
    "quantity", [0, -0.1, float("nan"), float("inf"), -float("inf"), True, "0.1"]
)
def test_rejects_quantity_that_bypassed_model_validation(quantity: object) -> None:
    engine = RiskEngine()
    original = make_intent()
    invalid = original.model_copy(update={"quantity": quantity})
    rejected = engine.evaluate(invalid)
    assert not rejected.approved
    assert rejected.reason == "invalid_quantity"
    assert rejected.approved_intent is None
    assert engine.decisions == (rejected,)
    # A rejected signal does not consume its idempotency key.
    assert engine.evaluate(original).approved


@pytest.mark.parametrize(
    "confidence", [-0.1, 1.1, float("nan"), float("inf"), -float("inf"), True, "0.9"]
)
def test_rejects_confidence_that_bypassed_model_validation(confidence: object) -> None:
    engine = RiskEngine()
    invalid = make_intent().model_copy(update={"confidence": confidence})
    decision = engine.evaluate(invalid)
    assert not decision.approved
    assert decision.reason == "invalid_confidence"
    assert decision.approved_intent is None
    assert engine.decisions == (decision,)


@pytest.mark.parametrize(
    "confidence, minimum, approved",
    [(0.0, 0.0, True), (1.0, 1.0, True), (0.7, 0.7, True), (0.69, 0.7, False)],
)
def test_confidence_boundaries(confidence: float, minimum: float, approved: bool) -> None:
    decision = RiskEngine(RiskLimits(min_confidence=minimum)).evaluate(
        make_intent(confidence=confidence, source="ai_assisted")
    )
    assert decision.approved is approved
    if not approved:
        assert decision.reason == "confidence_below_minimum"


def test_high_confidence_cannot_override_quantity_limit() -> None:
    decision = RiskEngine(RiskLimits(max_quantity=0.5)).evaluate(
        make_intent(quantity=0.6, confidence=1.0, source="ai_assisted")
    )
    assert not decision.approved
    assert decision.reason == "quantity_limit_exceeded"


def test_rejects_ai_intent_without_explicit_confidence_after_validation_bypass() -> None:
    intent = make_intent().model_copy(update={"source": "ai_assisted"})
    decision = RiskEngine().evaluate(intent)
    assert not decision.approved
    assert decision.reason == "invalid_intent"


def test_rejects_naive_intent_timestamp_after_validation_bypass() -> None:
    engine = RiskEngine()
    intent = make_intent().model_copy(update={"created_at": datetime(2026, 1, 1)})
    decision = engine.evaluate(intent)
    assert not decision.approved
    assert decision.reason == "invalid_timestamp"
    assert engine.decisions == (decision,)


def test_missing_signal_id_still_records_a_rejection() -> None:
    engine = RiskEngine()
    malformed = TradeIntent.model_construct(symbol="BTCUSDT", side="long", quantity=0.1)
    decision = engine.evaluate(malformed)
    assert not decision.approved
    assert decision.reason == "invalid_intent"
    assert decision.signal_id is None
    assert UUID(decision.decision_id).version == 4
    assert engine.decisions == (decision,)


def test_rejects_naive_evaluation_clock() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        RiskEngine().evaluate(make_intent(), now=datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_signal_age_seconds": -1},
        {"max_signal_age_seconds": 0.5},
        {"max_signal_age_seconds": float("inf")},
        {"max_signal_age_seconds": float("nan")},
        {"max_signal_age_seconds": True},
        {"max_quantity": 0},
        {"max_quantity": -1},
        {"max_quantity": float("nan")},
        {"max_quantity": float("inf")},
        {"max_quantity": True},
        {"min_confidence": -0.1},
        {"min_confidence": 1.1},
        {"min_confidence": float("nan")},
        {"min_confidence": float("inf")},
        {"min_confidence": True},
        {"execution_enabled": "false"},
        {"execution_enabled": 1},
    ],
)
def test_rejects_invalid_risk_limits(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RiskLimits(**overrides)


def test_quantity_at_limit_and_zero_age_limit_are_allowed() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    decision = RiskEngine(RiskLimits(max_signal_age_seconds=0, max_quantity=0.1)).evaluate(
        make_intent(created_at=now, quantity=0.1), now=now
    )
    assert decision.approved


def test_audit_history_retains_immutable_inputs_limits_and_decisions() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    intent = make_intent(created_at=now)
    limits = RiskLimits()
    engine = RiskEngine(limits)
    empty_snapshot = engine.decisions
    first = engine.evaluate(intent, now=now)
    second = engine.evaluate(intent, now=now + timedelta(seconds=1))

    assert empty_snapshot == ()
    assert engine.decisions == (first, second)
    assert first.decision_id != second.decision_id
    assert UUID(first.decision_id).version == 4
    assert UUID(second.decision_id).version == 4
    assert first.signal_id == second.signal_id == intent.signal_id
    assert first.evaluated_at == now
    assert second.evaluated_at == now + timedelta(seconds=1)
    assert first.intent == intent
    assert first.intent is not intent
    assert first.limits == limits
    assert first.reason == "approved"
    assert second.reason == "duplicate_signal"
    assert second.approved_intent is None
    with pytest.raises(FrozenInstanceError):
        first.reason = "changed"
    with pytest.raises(FrozenInstanceError):
        first.limits.max_quantity = 100.0
    with pytest.raises(ValidationError):
        first.intent.quantity = 100.0
    assert first.approved_intent is not None
    with pytest.raises(ValidationError):
        first.approved_intent.quantity = 100.0


def test_concurrent_duplicate_evaluations_approve_only_once() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    intent = make_intent(created_at=now)
    engine = RiskEngine()
    barrier = Barrier(8)

    def evaluate(_: int) -> bool:
        barrier.wait(timeout=5)
        return engine.evaluate(intent, now=now).approved

    with ThreadPoolExecutor(max_workers=8) as pool:
        approvals = list(pool.map(evaluate, range(8)))
    assert sum(approvals) == 1
    assert len(engine.decisions) == 8
    assert sum(item.reason == "duplicate_signal" for item in engine.decisions) == 7


def test_distinct_signals_can_each_be_approved() -> None:
    engine = RiskEngine()
    assert engine.evaluate(make_intent(signal_id="one")).approved
    assert engine.evaluate(make_intent(signal_id="two")).approved
