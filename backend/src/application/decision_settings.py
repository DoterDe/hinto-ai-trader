"""The four explicit eligibility gates, configured independently of scoring."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.decisions import DecisionPolicy


class DecisionSettings(BaseSettings, DecisionPolicy):
    model_config = SettingsConfigDict(env_prefix="DECISION_", frozen=True,
        allow_inf_nan=False, revalidate_instances="always", validate_default=True, extra="forbid")

    @field_validator("min_contributing_strategies", mode="before")
    @classmethod
    def environment_integer(cls, value: object) -> object:
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        return value

    @field_validator("block_incomplete_strategy_coverage", mode="before")
    @classmethod
    def environment_boolean(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value
