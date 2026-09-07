from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.application.risk_engine import RiskEngine, RiskLimits
from src.domain.models import ApprovedTradeIntent, SignalSide, TradeIntent, TradingMode
from src.infrastructure.paper_execution import PaperExecutionGateway


@pytest.fixture
def approved_intent() -> ApprovedTradeIntent:
    return ApprovedTradeIntent(
        signal_id="sig-paper-1",
        symbol="BTCUSDT",
        side=SignalSide.LONG,
        quantity=0.1,
    )


@pytest.mark.asyncio
async def test_paper_execution_records_fill(approved_intent: ApprovedTradeIntent) -> None:
    gateway = PaperExecutionGateway()

    result = await gateway.execute(approved_intent, reference_price=100_000.0)

    assert result.mode == TradingMode.PAPER
    assert result.fill_price == 100_000.0
    assert result.signal_id == approved_intent.signal_id
    assert result.symbol == approved_intent.symbol
    assert result.side == approved_intent.side
    assert result.quantity == approved_intent.quantity
    assert result.executed_at.utcoffset() is not None
    assert gateway.fills == (result,)


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), -float("inf"), True, None, "100"])
async def test_paper_execution_rejects_invalid_price(
    approved_intent: ApprovedTradeIntent, price: Any
) -> None:
    gateway = PaperExecutionGateway()

    with pytest.raises(ValueError, match="reference_price"):
        await gateway.execute(approved_intent, reference_price=price)

    assert gateway.fills == ()
    # Failed validation must not consume the signal ID.
    result = await gateway.execute(approved_intent, reference_price=100_000.0)
    assert gateway.fills == (result,)


@pytest.mark.asyncio
async def test_paper_execution_requires_approved_model(approved_intent: ApprovedTradeIntent) -> None:
    gateway = PaperExecutionGateway()
    unapproved = TradeIntent.model_validate(approved_intent.model_dump())

    for invalid_intent in (unapproved, approved_intent.model_dump(), None):
        with pytest.raises(TypeError, match="ApprovedTradeIntent"):
            await gateway.execute(invalid_intent, reference_price=100_000.0)

    assert gateway.fills == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": float("nan")},
        {"quantity": float("inf")},
        {"signal_id": ""},
        {"symbol": ""},
        {"side": "invalid"},
        {"confidence": float("nan")},
        {"created_at": datetime(2026, 1, 1)},
        {"approved_at": datetime(2026, 1, 1)},
    ],
)
async def test_paper_execution_revalidates_approval(
    approved_intent: ApprovedTradeIntent, updates: dict[str, Any]
) -> None:
    gateway = PaperExecutionGateway()
    malformed = approved_intent.model_copy(update=updates)

    with pytest.raises(ValidationError):
        await gateway.execute(malformed, reference_price=100_000.0)

    assert gateway.fills == ()


@pytest.mark.asyncio
async def test_identical_retry_returns_original_fill(approved_intent: ApprovedTradeIntent) -> None:
    gateway = PaperExecutionGateway()
    first = await gateway.execute(approved_intent, reference_price=100_000.0)
    retry = ApprovedTradeIntent.model_validate(approved_intent.model_dump())

    repeated = await gateway.execute(retry, reference_price=110_000.0)

    assert repeated is first
    assert repeated.fill_price == 100_000.0
    assert gateway.fills == (first,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"quantity": 0.2},
        {"symbol": "ETHUSDT"},
        {"side": SignalSide.SHORT},
        {"source": "ai_assisted", "confidence": 1.0},
        {"confidence": 0.9},
        {"approved_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ],
)
async def test_conflicting_signal_id_does_not_add_fill(
    approved_intent: ApprovedTradeIntent, updates: dict[str, Any]
) -> None:
    gateway = PaperExecutionGateway()
    first = await gateway.execute(approved_intent, reference_price=100_000.0)
    conflicting = approved_intent.model_copy(update=updates)

    with pytest.raises(ValueError, match="different approved intent"):
        await gateway.execute(conflicting, reference_price=110_000.0)

    assert gateway.fills == (first,)
    assert await gateway.execute(approved_intent, reference_price=90_000.0) is first


@pytest.mark.asyncio
async def test_fills_are_immutable_snapshots(approved_intent: ApprovedTradeIntent) -> None:
    gateway = PaperExecutionGateway()
    empty_snapshot = gateway.fills
    first = await gateway.execute(approved_intent, reference_price=100_000.0)
    first_snapshot = gateway.fills

    assert isinstance(first_snapshot, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        first.fill_price = 1.0

    second = await gateway.execute(
        approved_intent.model_copy(update={"signal_id": "sig-paper-2"}),
        reference_price=110_000.0,
    )

    assert empty_snapshot == ()
    assert first_snapshot == (first,)
    assert gateway.fills == (first, second)
    assert first.execution_id != second.execution_id
    assert first.fill_price == 100_000.0


@pytest.mark.asyncio
async def test_risk_approved_intent_executes_once() -> None:
    now = datetime.now(timezone.utc)
    intent = TradeIntent(
        signal_id="sig-risk-paper",
        symbol="BTCUSDT",
        side=SignalSide.LONG,
        quantity=0.1,
        created_at=now,
    )
    engine = RiskEngine()
    gateway = PaperExecutionGateway()

    decision = engine.evaluate(intent, now=now)
    assert decision.approved
    assert decision.approved_intent is not None
    result = await gateway.execute(decision.approved_intent, reference_price=100_000.0)
    duplicate = engine.evaluate(intent, now=now)

    assert not duplicate.approved
    assert duplicate.approved_intent is None
    with pytest.raises(TypeError, match="ApprovedTradeIntent"):
        await gateway.execute(duplicate.approved_intent, reference_price=100_000.0)
    assert gateway.fills == (result,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limits", "quantity", "age_seconds", "confidence"),
    [
        (RiskLimits(execution_enabled=False), 0.1, 0, 1.0),
        (RiskLimits(), 2.0, 0, 1.0),
        (RiskLimits(), 0.1, 31, 1.0),
        (RiskLimits(), 0.1, -1, 1.0),
        (RiskLimits(min_confidence=0.7), 0.1, 0, 0.6),
    ],
)
async def test_risk_rejected_intents_cannot_execute(
    limits: RiskLimits, quantity: float, age_seconds: int, confidence: float
) -> None:
    now = datetime.now(timezone.utc)
    intent = TradeIntent(
        signal_id="sig-rejected-paper",
        symbol="BTCUSDT",
        side=SignalSide.LONG,
        quantity=quantity,
        created_at=now - timedelta(seconds=age_seconds),
        confidence=confidence,
        source="ai_assisted",
    )
    gateway = PaperExecutionGateway()

    decision = RiskEngine(limits).evaluate(intent, now=now)

    assert not decision.approved
    assert decision.approved_intent is None
    for invalid_intent in (intent, decision.approved_intent):
        with pytest.raises(TypeError, match="ApprovedTradeIntent"):
            await gateway.execute(invalid_intent, reference_price=100_000.0)
    assert gateway.fills == ()
