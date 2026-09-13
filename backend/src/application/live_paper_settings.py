"""Bounded live telemetry and batching settings; no execution configuration."""

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LivePaperSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIVE_PAPER_", frozen=True,
        extra="forbid", allow_inf_nan=False, validate_default=True, revalidate_instances="always")

    enabled: Annotated[bool, Field(strict=True)] = True
    batch_timeout_ms: Annotated[int, Field(strict=True, gt=0, le=60000)] = 1500
    event_history_limit: Annotated[int, Field(strict=True, gt=0, le=10000)] = 1000
    curve_history_limit: Annotated[int, Field(strict=True, gt=0, le=20000)] = 2000
    position_history_limit: Annotated[int, Field(strict=True, gt=0, le=10000)] = 1000
    pending_batch_limit: Annotated[int, Field(strict=True, gt=0, le=64)] = 8
    queue_limit: Annotated[int, Field(strict=True, gt=0, le=10000)] = 1000

    @field_validator("enabled", mode="before")
    @classmethod
    def boolean(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value

    @field_validator("batch_timeout_ms", "event_history_limit", "curve_history_limit",
                     "position_history_limit", "pending_batch_limit", "queue_limit", mode="before")
    @classmethod
    def integer(cls, value: object) -> object:
        return int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else value
