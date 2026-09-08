from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _environment_integer(value: object) -> object:
    # Environment strings are accepted; bools and floating-point periods aren't.
    return int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else value


Period = Annotated[int, Field(strict=True, gt=0), BeforeValidator(_environment_integer)]


class FeatureSettings(BaseSettings):
    """Exchange-independent windows. Environment overrides use FEATURE_* names."""

    model_config = SettingsConfigDict(env_prefix="FEATURE_", frozen=True, extra="ignore")

    ema_fast: Period = 9
    ema_slow: Period = 21
    ema_long: Period = 50
    rsi_period: Period = 14
    atr_period: Period = 14
    roc_period: Period = 10
    volatility_window: Period = 20
    relative_volume_window: Period = 20
    vwap_window: Period = 20
    rolling_return_windows: tuple[Period, ...] = (5, 10, 20)
    history_limit: Period = 500

    @model_validator(mode="after")
    def coherent_windows(self) -> Self:
        if not self.ema_fast < self.ema_slow < self.ema_long:
            raise ValueError("EMA periods must satisfy fast < slow < long")
        if self.volatility_window < 2:
            raise ValueError("volatility_window requires at least two returns")
        if not self.rolling_return_windows or tuple(sorted(set(self.rolling_return_windows))) != self.rolling_return_windows:
            raise ValueError("rolling_return_windows must be nonempty, unique and increasing")
        required = max(self.ema_long, self.rsi_period + 1, self.atr_period,
                       self.roc_period + 1, self.volatility_window + 1,
                       self.relative_volume_window + 1, self.vwap_window,
                       self.rolling_return_windows[-1] + 1)
        if self.history_limit < required:
            raise ValueError("history_limit is insufficient for configured windows")
        return self
