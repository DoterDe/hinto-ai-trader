"""Fixed virtual-capital assumptions; no inferred probability or fitting."""

from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PaperPortfolioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTFOLIO_", frozen=True, extra="forbid",
        allow_inf_nan=False, validate_default=True, revalidate_instances="always")

    initial_virtual_equity: Annotated[Decimal, Field(gt=0)] = Decimal(100000)
    target_position_fraction: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.10")
    max_gross_exposure_fraction: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.40")
    max_symbol_exposure_fraction: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.15")
    max_open_positions: Annotated[int, Field(strict=True, gt=0)] = 4
    max_drawdown_fraction: Annotated[Decimal, Field(gt=0, lt=1)] = Decimal("0.20")
    one_position_per_symbol: Annotated[bool, Field(strict=True)] = True

    @field_validator("max_open_positions", mode="before")
    @classmethod
    def environment_integer(cls, value: object) -> object:
        return int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else value

    @field_validator("one_position_per_symbol", mode="before")
    @classmethod
    def environment_boolean(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value

    @model_validator(mode="after")
    def supported_limits(self) -> Self:
        if self.max_symbol_exposure_fraction > self.max_gross_exposure_fraction:
            raise ValueError("symbol exposure cannot exceed gross exposure limit")
        if not self.one_position_per_symbol:
            raise ValueError("multiple same-symbol positions are unsupported in Phase 7")
        return self
