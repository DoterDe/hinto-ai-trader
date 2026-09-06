from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.domain.models import ApprovedTradeIntent, TradeIntent


@dataclass(frozen=True)
class RiskLimits:
    max_signal_age_seconds: int = 30
    max_quantity: float = 1.0
    execution_enabled: bool = True


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    approved_intent: ApprovedTradeIntent | None = None


class RiskEngine:
    """Deterministic pre-execution guard.

    Signal IDs are treated as idempotency keys. Once an intent is approved,
    the same signal ID cannot be approved again by this engine instance.
    """

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()
        self._approved_signal_ids: set[str] = set()

    def evaluate(
        self,
        intent: TradeIntent,
        *,
        now: datetime | None = None,
    ) -> RiskDecision:
        current_time = now or datetime.now(timezone.utc)

        if not self._limits.execution_enabled:
            return RiskDecision(False, "execution_disabled")

        if intent.signal_id in self._approved_signal_ids:
            return RiskDecision(False, "duplicate_signal")

        age = current_time - intent.created_at
        max_age = timedelta(seconds=self._limits.max_signal_age_seconds)
        if age < timedelta(0) or age > max_age:
            return RiskDecision(False, "stale_or_future_signal")

        if intent.quantity <= 0:
            return RiskDecision(False, "invalid_quantity")

        if intent.quantity > self._limits.max_quantity:
            return RiskDecision(False, "quantity_limit_exceeded")

        approved = ApprovedTradeIntent(**intent.model_dump())
        self._approved_signal_ids.add(intent.signal_id)
        return RiskDecision(True, "approved", approved)
