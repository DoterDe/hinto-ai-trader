from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
Symbol = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32)
]


class DomainModel(BaseModel):
    """Immutable domain values, revalidated when crossing service boundaries."""

    model_config = ConfigDict(
        frozen=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class TradingMode(str, Enum):
    PAPER = "paper"
    TESTNET = "testnet"


class SignalSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class AIDecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    NEUTRAL = "neutral"


class SignalCandidate(DomainModel):
    signal_id: Identifier
    symbol: Symbol
    side: SignalSide
    score: float = Field(strict=True, ge=0.0, le=100.0)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIDecision(DomainModel):
    decision: AIDecisionType
    confidence: float = Field(strict=True, ge=0.0, le=1.0)
    risk_flags: tuple[str, ...] = ()
    reason: str = Field(default="", max_length=500)


class TradeIntent(DomainModel):
    signal_id: Identifier
    symbol: Symbol
    side: SignalSide
    quantity: float = Field(strict=True, gt=0.0)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["strategy", "ai_assisted"] = "strategy"
    confidence: float = Field(default=1.0, strict=True, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_ai_confidence(self) -> Self:
        if self.source == "ai_assisted" and "confidence" not in self.model_fields_set:
            raise ValueError("ai_assisted intents require explicit confidence")
        return self


class ApprovedTradeIntent(TradeIntent):
    approved_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(DomainModel):
    execution_id: Identifier
    signal_id: Identifier
    symbol: Symbol
    side: SignalSide
    quantity: float = Field(strict=True, gt=0.0)
    fill_price: float = Field(strict=True, gt=0.0)
    mode: TradingMode
    executed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
