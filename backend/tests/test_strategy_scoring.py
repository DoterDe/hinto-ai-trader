from decimal import Decimal, localcontext

import pytest

from src.strategies.scoring import clamp, dead_zone_score, linear_quality, number, sign, signed_score


@pytest.mark.parametrize("value,expected", [(-2, 0), (0, 0), ("0.5", "0.5"), (1, 1), (2, 1)])
def test_clamp_boundaries(value: object, expected: object) -> None:
    assert clamp(value) == Decimal(expected)
    assert clamp(value, -1, 1) == max(Decimal(-1), min(Decimal(1), Decimal(value)))


@pytest.mark.parametrize("value,expected", [(-100, -1), (-10, -1), (-6, "-0.5"), (-2, 0),
    (0, 0), (2, 0), (6, "0.5"), (10, 1), (100, 1)])
def test_signed_ramp_and_exact_neutral_thresholds(value: int, expected: object) -> None:
    assert signed_score(value, 2, 10) == Decimal(expected)


@pytest.mark.parametrize("value,expected", [(0, -1), (30, -1), ("37.5", "-0.5"), (45, 0),
    (50, 0), (55, 0), ("62.5", "0.5"), (70, 1), (100, 1)])
def test_asymmetric_dead_zone_uses_native_thresholds(value: object, expected: object) -> None:
    assert dead_zone_score(value, 30, 45, 55, 70) == Decimal(expected)


def test_quality_increasing_ramp() -> None:
    assert linear_quality("0.1", "0.25", "0.55") == 0
    assert linear_quality("0.25", "0.25", "0.55") == 0
    assert linear_quality("0.4", "0.25", "0.55") == Decimal("0.5")
    assert linear_quality("0.55", "0.25", "0.55") == 1
    assert linear_quality("0.9", "0.25", "0.55") == 1


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", float("nan"),
    float("inf"), True, None, "not-a-number"])
def test_invalid_values_never_become_directional_evidence(value: object) -> None:
    for function in (number, clamp, sign):
        with pytest.raises(ValueError):
            function(value)
    with pytest.raises(ValueError):
        signed_score(value, 0, 1)
    with pytest.raises(ValueError):
        dead_zone_score(value, 30, 45, 55, 70)


@pytest.mark.parametrize("arguments", [(1, 0), (1, 1), (-1, 2)])
def test_invalid_signed_thresholds(arguments: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        signed_score(1, *arguments)


def test_invalid_ranges_and_nonfinite_bounds() -> None:
    with pytest.raises(ValueError):
        clamp(1, 2, 0)
    with pytest.raises(ValueError):
        clamp(1, 0, "Infinity")
    with pytest.raises(ValueError):
        linear_quality(1, 1, 1)
    with pytest.raises(ValueError):
        dead_zone_score(50, 30, 55, 45, 70)


def test_saturation_precedes_extreme_arithmetic() -> None:
    assert signed_score(Decimal("1e1000000"), "0.1", 2) == 1
    assert signed_score(Decimal("-1e1000000"), "0.1", 2) == -1
    assert signed_score(Decimal("1e-1000000"), "0.1", 2) == 0
    assert clamp(Decimal("1e1000000")) == 1


def test_float_conversion_and_caller_context_are_explicit() -> None:
    assert number(0.1) == Decimal("0.1")
    with localcontext() as context:
        context.prec = 3
        assert signed_score(1, 0, 3) == Decimal("0.3333333333333333333333333333333333")
        assert linear_quality(1, 0, 3) == Decimal("0.3333333333333333333333333333333333")


def test_inexact_underflow_is_rejected() -> None:
    with pytest.raises(ValueError):
        linear_quality(Decimal("1e-2000000"), 0, 1)
