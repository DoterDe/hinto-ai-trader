from datetime import datetime, timedelta, timezone

from src.application.risk_engine import RiskEngine, RiskLimits
from src.domain.models import SignalSide, TradeIntent


def make_intent(**overrides) -> TradeIntent:
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
