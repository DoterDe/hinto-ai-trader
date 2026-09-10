from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from src.application.backtest_math import outcome_returns
from src.application.backtest_settings import BacktestSettings
from src.domain.backtesting import OutcomeReturns


@pytest.mark.parametrize("direction,exit,fee,slip,effective_entry,effective_exit,gross,slippage_cost,fee_cost,net", [
    ("LONG", "110", 0, 0, "100", "110", ".1", "0", "0", ".1"),
    ("SHORT", "90", 0, 0, "100", "90", ".1", "0", "0", ".1"),
    ("LONG", "90", 0, 0, "100", "90", "-.1", "0", "0", "-.1"),
    ("SHORT", "110", 0, 0, "100", "110", "-.1", "0", "0", "-.1"),
    ("LONG", "110", 5, 0, "100", "110", ".1", "0", ".00105", ".09895"),
    ("SHORT", "90", 5, 0, "100", "90", ".1", "0", ".00095", ".09905"),
    ("LONG", "110", 0, 2, "100.02", "109.978", ".1", ".00042", "0", ".09958"),
    ("SHORT", "90", 0, 2, "99.98", "90.018", ".1", ".00038", "0", ".09962"),
    ("LONG", "110", 5, 2, "100.02", "109.978", ".1", ".00042", ".00104999", ".09853001"),
    ("SHORT", "90", 5, 2, "99.98", "90.018", ".1", ".00038", ".00094999", ".09867001"),
    ("SHORT", "110", 5, 2, "99.98", "110.022", "-.1", ".00042", ".00105001", "-.10147001"),
    ("LONG", "100", 5, 2, "100.02", "99.98", "0", ".0004", ".001", "-.0014"),
    ("SHORT", "100", 5, 2, "99.98", "100.02", "0", ".0004", ".001", "-.0014"),
])
def test_independent_exact_directional_cost_examples(direction, exit, fee, slip, effective_entry,
        effective_exit, gross, slippage_cost, fee_cost, net):
    result = outcome_returns(Decimal(100), Decimal(exit), direction,
        BacktestSettings(fee_bps_per_side=fee, slippage_bps_per_side=slip))
    assert result.effective_entry_price == Decimal(effective_entry)
    assert result.effective_exit_price == Decimal(effective_exit)
    assert result.gross_return == Decimal(gross)
    assert result.slippage_cost_return == Decimal(slippage_cost)
    assert result.fee_cost_return == Decimal(fee_cost)
    assert result.net_return == Decimal(net)
    assert result.simulated_cost_return == Decimal(gross) - Decimal(net)
    assert OutcomeReturns.model_validate_json(result.model_dump_json()) == result


def test_math_is_independent_of_caller_decimal_precision():
    with localcontext() as context:
        context.prec = 4
        context.rounding = "ROUND_DOWN"
        result = outcome_returns(Decimal(100), Decimal(110), "LONG", BacktestSettings())
        assert result.net_return == Decimal(".09853001")
        assert context.prec == 4 and context.rounding == "ROUND_DOWN"


@pytest.mark.parametrize("entry,exit,direction", [
    (0, 1, "LONG"), (-1, 1, "LONG"), (1, "NaN", "LONG"), (1, "Infinity", "SHORT"),
    (True, 1, "LONG"), (1, 1, "NEUTRAL"), (1, 1, "BUY"),
])
def test_invalid_prices_and_direction_fail(entry, exit, direction):
    with pytest.raises(ValueError):
        outcome_returns(entry, exit, direction, BacktestSettings())


def test_invalid_settings_copy_and_unrepresentable_arithmetic_fail_closed():
    with pytest.raises(ValueError):
        outcome_returns(100, 110, "LONG", BacktestSettings().model_copy(update={"fee_bps_per_side": -1}))
    with pytest.raises(ValueError, match="arithmetic"):
        outcome_returns(Decimal("1e-999999"), Decimal("1e999999"), "LONG", BacktestSettings())


@pytest.mark.parametrize("field", list(OutcomeReturns.model_fields))
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_return_fields_are_rejected(field, value):
    result = outcome_returns(100, 110, "LONG", BacktestSettings())
    with pytest.raises(ValidationError):
        OutcomeReturns.model_validate(result.model_copy(update={field: value}))


def test_inconsistent_cost_or_net_records_fail_validation():
    result = outcome_returns(100, 110, "LONG", BacktestSettings())
    for field in ("simulated_cost_return", "net_return"):
        with pytest.raises(ValidationError, match="reconcile"):
            OutcomeReturns.model_validate(result.model_copy(update={field: Decimal(0)}))
