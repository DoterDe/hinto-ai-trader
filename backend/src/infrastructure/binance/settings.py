from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.infrastructure.binance.stream_router import (
    DEFAULT_BASE_URL, DEFAULT_SYMBOLS, KLINE_INTERVALS,
    build_connections, normalize_symbols, validate_base_url,
)


class MarketDataSettings(BaseSettings):
    """Public feed settings only; environment symbols use a JSON array."""

    model_config = SettingsConfigDict(
        env_prefix="BINANCE_MARKET_DATA_", frozen=True, allow_inf_nan=False,
        extra="ignore", hide_input_in_errors=True,
    )

    enabled: bool = True
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    kline_interval: str = "1m"
    stale_after_seconds: float = Field(default=10.0, gt=0)
    reconnect_min_delay: float = Field(default=1.0, gt=0)
    reconnect_max_delay: float = Field(default=30.0, gt=0)
    open_timeout: float = Field(default=10.0, gt=0)
    close_timeout: float = Field(default=5.0, gt=0)
    receive_timeout: float = Field(default=30.0, gt=0)
    rotate_after_seconds: float = Field(default=86100.0, gt=0, lt=86400)
    websocket_base_url: str = DEFAULT_BASE_URL

    @field_validator("symbols")
    @classmethod
    def valid_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return normalize_symbols(value)

    @field_validator("kline_interval")
    @classmethod
    def valid_interval(cls, value: str) -> str:
        if value not in KLINE_INTERVALS:
            raise ValueError("unsupported kline interval")
        return value

    @field_validator("websocket_base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return validate_base_url(value)

    @model_validator(mode="after")
    def consistent_settings(self) -> Self:
        if self.reconnect_max_delay < self.reconnect_min_delay:
            raise ValueError("reconnect_max_delay must be >= reconnect_min_delay")
        build_connections(self.symbols, kline_intervals=(self.kline_interval,))
        return self
