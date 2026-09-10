"""Fixed validation assumptions; no parameter search or return-based fitting."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BACKTEST_", frozen=True, extra="forbid",
        allow_inf_nan=False, validate_default=True, revalidate_instances="always")

    holding_period_bars: Annotated[int, Field(strict=True, gt=0)] = 5
    fee_bps_per_side: Annotated[Decimal, Field(ge=0)] = Decimal(5)
    # At 100% adverse slippage a positive effective price ceases to exist.
    slippage_bps_per_side: Annotated[Decimal, Field(ge=0, lt=10000)] = Decimal(2)
    chronological_segments: Annotated[int, Field(strict=True, ge=1, le=100)] = 4

    @field_validator("holding_period_bars", "chronological_segments", mode="before")
    @classmethod
    def environment_integer(cls, value: object) -> object:
        return int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else value
