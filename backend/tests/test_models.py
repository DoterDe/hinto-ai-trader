from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.domain.models import (
    AIDecision,
    ApprovedTradeIntent,
    DomainModel,
    ExecutionResult,
    SignalCandidate,
    TradeIntent,
    TradingMode,
)


INTENT_VALUES: dict[str, Any] = {
    "signal_id": "signal-1",
    "symbol": "BTCUSDT",
    "side": "long",
    "quantity": 0.1,
}
SIGNAL_VALUES: dict[str, Any] = {
    "signal_id": "signal-1",
    "symbol": "BTCUSDT",
    "side": "long",
    "score": 75.0,
}
FILL_VALUES: dict[str, Any] = {
    **INTENT_VALUES,
    "execution_id": "fill-1",
    "fill_price": 100_000.0,
    "mode": "paper",
}
MODEL_CASES = [
    (SignalCandidate, SIGNAL_VALUES),
    (AIDecision, {"decision": "approve", "confidence": 0.8}),
    (TradeIntent, INTENT_VALUES),
    (ApprovedTradeIntent, INTENT_VALUES),
    (ExecutionResult, FILL_VALUES),
]
TIMESTAMP_CASES = [
    (SignalCandidate, SIGNAL_VALUES, "created_at"),
    (TradeIntent, INTENT_VALUES, "created_at"),
    (ApprovedTradeIntent, INTENT_VALUES, "created_at"),
    (ApprovedTradeIntent, INTENT_VALUES, "approved_at"),
    (ExecutionResult, FILL_VALUES, "executed_at"),
]
NUMERIC_CASES = [
    (SignalCandidate, SIGNAL_VALUES, "score"),
    (AIDecision, {"decision": "approve", "confidence": 0.8}, "confidence"),
    (TradeIntent, INTENT_VALUES, "quantity"),
    (TradeIntent, INTENT_VALUES, "confidence"),
    (ExecutionResult, FILL_VALUES, "quantity"),
    (ExecutionResult, FILL_VALUES, "fill_price"),
]


@pytest.mark.parametrize("model,values", MODEL_CASES)
def test_domain_models_cannot_be_mutated(
    model: type[DomainModel], values: dict[str, Any]
) -> None:
    value = model(**values)
    field = next(iter(values))

    with pytest.raises(ValidationError, match="frozen"):
        setattr(value, field, values[field])


@pytest.mark.parametrize("model,values,field", NUMERIC_CASES)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_numeric_values_must_be_finite(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: float
) -> None:
    with pytest.raises(ValidationError):
        model(**(values | {field: invalid}))


@pytest.mark.parametrize("model,values,field", NUMERIC_CASES)
@pytest.mark.parametrize("invalid", [True, False, "1"])
def test_numeric_fields_reject_booleans_and_strings(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: Any
) -> None:
    with pytest.raises(ValidationError):
        model(**(values | {field: invalid}))


@pytest.mark.parametrize("model,values,field", NUMERIC_CASES)
@pytest.mark.parametrize("numeric", [1, 0.5])
def test_numeric_fields_accept_integers_and_floats(
    model: type[DomainModel], values: dict[str, Any], field: str, numeric: int | float
) -> None:
    assert getattr(model(**(values | {field: numeric})), field) == numeric


@pytest.mark.parametrize("model,values,field", NUMERIC_CASES)
@pytest.mark.parametrize("invalid", [True, "1", 10**400])
def test_instance_revalidation_rejects_malformed_numeric_fields(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: Any
) -> None:
    unvalidated = model(**values).model_copy(update={field: invalid})
    with pytest.raises(ValidationError):
        model.model_validate(unvalidated)


@pytest.mark.parametrize(
    "model,values,field",
    [
        (TradeIntent, INTENT_VALUES, "quantity"),
        (ExecutionResult, FILL_VALUES, "quantity"),
        (ExecutionResult, FILL_VALUES, "fill_price"),
    ],
)
@pytest.mark.parametrize("invalid", [0.0, -0.1])
def test_quantities_and_prices_must_be_positive(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: float
) -> None:
    with pytest.raises(ValidationError):
        model(**(values | {field: invalid}))


@pytest.mark.parametrize("invalid", [-0.01, 1.01])
@pytest.mark.parametrize("model", [TradeIntent, AIDecision])
def test_confidence_rejects_out_of_range_values(
    model: type[DomainModel], invalid: float
) -> None:
    values = INTENT_VALUES if model is TradeIntent else {"decision": "approve"}
    with pytest.raises(ValidationError):
        model(**(values | {"confidence": invalid}))


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_accepts_inclusive_bounds(confidence: float) -> None:
    intent = TradeIntent(**INTENT_VALUES, confidence=confidence)
    advice = AIDecision(decision="approve", confidence=confidence)
    assert intent.confidence == advice.confidence == confidence


def test_ai_assisted_intents_require_explicit_confidence() -> None:
    assert TradeIntent(**INTENT_VALUES).confidence == 1.0
    with pytest.raises(ValidationError, match="explicit confidence"):
        TradeIntent(**INTENT_VALUES, source="ai_assisted")
    intent = TradeIntent(**INTENT_VALUES, source="ai_assisted", confidence=0.8)
    assert TradeIntent.model_validate(intent).confidence == 0.8


def test_revalidation_rejects_ai_source_added_without_confidence() -> None:
    intent = TradeIntent(**INTENT_VALUES).model_copy(update={"source": "ai_assisted"})
    with pytest.raises(ValidationError, match="explicit confidence"):
        TradeIntent.model_validate(intent)


@pytest.mark.parametrize("model,values,field", TIMESTAMP_CASES)
@pytest.mark.parametrize("invalid", [datetime(2026, 1, 1), "2026-01-01T00:00:00"])
def test_timestamps_require_timezone(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: Any
) -> None:
    with pytest.raises(ValidationError):
        model(**(values | {field: invalid}))


@pytest.mark.parametrize("model,values,field", TIMESTAMP_CASES)
def test_timestamp_defaults_are_aware_and_explicit_offsets_are_supported(
    model: type[DomainModel], values: dict[str, Any], field: str
) -> None:
    default_timestamp = getattr(model(**values), field)
    assert default_timestamp.utcoffset() == timedelta(0)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    assert getattr(model(**(values | {field: timestamp})), field) == timestamp


@pytest.mark.parametrize(
    "model,values,field",
    [
        (SignalCandidate, SIGNAL_VALUES, "signal_id"),
        (SignalCandidate, SIGNAL_VALUES, "symbol"),
        (TradeIntent, INTENT_VALUES, "signal_id"),
        (TradeIntent, INTENT_VALUES, "symbol"),
        (ExecutionResult, FILL_VALUES, "execution_id"),
        (ExecutionResult, FILL_VALUES, "signal_id"),
        (ExecutionResult, FILL_VALUES, "symbol"),
    ],
)
@pytest.mark.parametrize("invalid", ["", " \t\n "])
def test_identifiers_and_symbols_cannot_be_blank(
    model: type[DomainModel], values: dict[str, Any], field: str, invalid: str
) -> None:
    with pytest.raises(ValidationError):
        model(**(values | {field: invalid}))


def test_identifiers_and_symbols_are_trimmed_before_validation() -> None:
    intent = TradeIntent(**(INTENT_VALUES | {"signal_id": " signal-1 ", "symbol": " BTCUSDT "}))
    assert intent.signal_id == "signal-1"
    assert intent.symbol == "BTCUSDT"
    with pytest.raises(ValidationError):
        TradeIntent(**(INTENT_VALUES | {"symbol": " x "}))


@pytest.mark.parametrize("model", [TradeIntent, ApprovedTradeIntent])
@pytest.mark.parametrize("bypass", ["copy", "construct"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1])
def test_model_validation_rechecks_instances_created_without_validation(
    model: type[TradeIntent], bypass: str, invalid: float
) -> None:
    original = model(**INTENT_VALUES)
    if bypass == "copy":
        unvalidated = original.model_copy(update={"quantity": invalid})
    else:
        unvalidated = model.model_construct(**(original.model_dump() | {"quantity": invalid}))
    with pytest.raises(ValidationError):
        model.model_validate(unvalidated)


def test_risk_flags_are_immutable_and_detached_from_input() -> None:
    flags = ["high_volatility"]
    advice = AIDecision(decision="neutral", confidence=0.5, risk_flags=flags)
    flags.append("stale_data")
    assert advice.risk_flags == ("high_volatility",)
    with pytest.raises(ValidationError, match="frozen"):
        advice.risk_flags += ("stale_data",)


def test_trading_modes_exclude_live_execution() -> None:
    assert {mode.value for mode in TradingMode} == {"paper", "testnet"}
    with pytest.raises(ValidationError):
        ExecutionResult(**(FILL_VALUES | {"mode": "live"}))
