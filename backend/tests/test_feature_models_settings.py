from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.application.feature_settings import FeatureSettings
from src.domain.features import FeatureGroup, Readiness, ReturnFeatures, TradeFeatures


def test_default_windows_and_capacity() -> None:
    settings = FeatureSettings()
    assert (settings.ema_fast, settings.ema_slow, settings.ema_long) == (9, 21, 50)
    assert (settings.rsi_period, settings.atr_period, settings.roc_period) == (14, 14, 10)
    assert (settings.volatility_window, settings.relative_volume_window, settings.vwap_window) == (20, 20, 20)
    assert settings.rolling_return_windows == (5, 10, 20)
    assert settings.history_limit == 500


@pytest.mark.parametrize("name", tuple(FeatureSettings.model_fields))
@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("inf"), float("nan")])
def test_invalid_periods(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        FeatureSettings(**{name: (value,) if name == "rolling_return_windows" else value})


@pytest.mark.parametrize("settings", [
    {"ema_fast": 21}, {"ema_slow": 50}, {"history_limit": 49},
    {"rsi_period": 500}, {"volatility_window": 1}, {"rolling_return_windows": ()},
    {"rolling_return_windows": (5, 5)}, {"rolling_return_windows": (10, 5)},
])
def test_incoherent_windows(settings: dict) -> None:
    with pytest.raises(ValidationError):
        FeatureSettings(**settings)


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_RSI_PERIOD", "7")
    monkeypatch.setenv("FEATURE_ROLLING_RETURN_WINDOWS", "[2, 4, 8]")
    assert FeatureSettings().rsi_period == 7
    assert FeatureSettings().rolling_return_windows == (2, 4, 8)


def test_feature_group_is_immutable_and_round_trips() -> None:
    group = FeatureGroup[TradeFeatures](state=Readiness.READY, available_samples=1,
                                       values=TradeFeatures(price="1.123456789012345678", quantity="2"))
    assert FeatureGroup[TradeFeatures].model_validate_json(group.model_dump_json()) == group
    with pytest.raises(ValidationError):
        group.values.price = Decimal(2)


@pytest.mark.parametrize("state", [Readiness.WARMING_UP, Readiness.STALE, Readiness.UNAVAILABLE, Readiness.PARTIAL])
def test_unready_values_are_forbidden(state: Readiness) -> None:
    with pytest.raises(ValidationError):
        FeatureGroup[TradeFeatures](state=state, reasons=("missing",), values=TradeFeatures(price=1, quantity=2))


def test_ready_requires_values_and_unready_requires_reason() -> None:
    with pytest.raises(ValidationError):
        FeatureGroup[TradeFeatures](state=Readiness.READY)
    with pytest.raises(ValidationError):
        FeatureGroup[TradeFeatures](state=Readiness.STALE)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_output_values_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        TradeFeatures(price=value, quantity=1)
    with pytest.raises(ValidationError):
        ReturnFeatures(close=1, simple_return=0, log_return=float(value), rolling_returns=())
