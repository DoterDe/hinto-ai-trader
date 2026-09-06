from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class SignalCandidate(BaseModel):
    signal_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=3, max_length=32)
    side: SignalSide
    score: float = Field(ge=0.0, le=100.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class AIDecision(BaseModel):
    decision: AIDecisionType
    confidence: float = Field(ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=500)


class TradeIntent(BaseModel):
    signal_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=3, max_length=32)
    side: SignalSide
    quantity: float = Field(gt=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["strategy", "ai_assisted"] = "strategy"


class ApprovedTradeIntent(TradeIntent):
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(BaseModel):
    execution_id: str
    signal_id: str
    symbol: str
    side: SignalSide
    quantity: float
    fill_price: float = Field(gt=0.0)
    mode: TradingMode
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
