from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from src.domain.models import ApprovedTradeIntent, TradeIntent


@dataclass(frozen=True)
class RiskLimits:
    max_signal_age_seconds: int = 30
    max_quantity: float = 1.0
    execution_enabled: bool = True
    min_confidence: float = 0.0

    def __post_init__(self) -> None:
        if (
            type(self.max_signal_age_seconds) is not int
            or self.max_signal_age_seconds < 0
        ):
            raise ValueError("max_signal_age_seconds must be a nonnegative integer")
        if not _finite_number(self.max_quantity) or self.max_quantity <= 0:
            raise ValueError("max_quantity must be finite and positive")
        if not _finite_number(self.min_confidence) or not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be finite and between 0 and 1")
        if type(self.execution_enabled) is not bool:
            raise ValueError("execution_enabled must be a boolean")


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    signal_id: str | None
    evaluated_at: datetime
    intent: TradeIntent
    limits: RiskLimits
    approved_intent: ApprovedTradeIntent | None = None
    decision_id: str = field(default_factory=lambda: str(uuid4()))


class RiskEngine:
    """Deterministic pre-execution guard.

    Signal IDs are treated as idempotency keys. Once an intent is approved,
    the same signal ID cannot be approved again by this engine instance.
    """

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()
        self._approved_signal_ids: set[str] = set()
        self._decisions: list[RiskDecision] = []
        self._lock = Lock()

    @property
    def decisions(self) -> tuple[RiskDecision, ...]:
        """Process-local history of every approval and rejection."""
        with self._lock:
            return tuple(self._decisions)

    def evaluate(
        self,
        intent: TradeIntent,
        *,
        now: datetime | None = None,
    ) -> RiskDecision:
        if not isinstance(intent, TradeIntent):
            raise TypeError("intent must be a TradeIntent")
        current_time = now if now is not None else datetime.now(timezone.utc)
        if not isinstance(current_time, datetime) or current_time.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        # Keep duplicate checking, approval, and audit recording atomic.
        with self._lock:
            try:
                validated = TradeIntent.model_validate(intent)
            except ValidationError as error:
                invalid_fields = {item["loc"][0] for item in error.errors() if item["loc"]}
                reason = "invalid_intent"
                for field_name, field_reason in (
                    ("quantity", "invalid_quantity"),
                    ("confidence", "invalid_confidence"),
                    ("created_at", "invalid_timestamp"),
                ):
                    if field_name in invalid_fields:
                        reason = field_reason
                        break
                return self._record(intent, current_time, reason)

            reason = self._rejection_reason(validated, current_time)
            if reason is not None:
                return self._record(validated, current_time, reason)

            approved = ApprovedTradeIntent(
                **validated.model_dump(), approved_at=current_time
            )
            self._approved_signal_ids.add(validated.signal_id)
            return self._record(validated, current_time, "approved", approved)

    def _rejection_reason(self, intent: TradeIntent, now: datetime) -> str | None:
        if not self._limits.execution_enabled:
            return "execution_disabled"
        if intent.signal_id in self._approved_signal_ids:
            return "duplicate_signal"
        age_seconds = (now - intent.created_at).total_seconds()
        if age_seconds < 0 or age_seconds > self._limits.max_signal_age_seconds:
            return "stale_or_future_signal"
        if intent.quantity > self._limits.max_quantity:
            return "quantity_limit_exceeded"
        if intent.confidence < self._limits.min_confidence:
            return "confidence_below_minimum"
        return None

    def _record(
        self,
        intent: TradeIntent,
        now: datetime,
        reason: str,
        approved_intent: ApprovedTradeIntent | None = None,
    ) -> RiskDecision:
        decision = RiskDecision(
            approved=approved_intent is not None,
            reason=reason,
            signal_id=(
                intent.signal_id
                if isinstance(getattr(intent, "signal_id", None), str)
                else None
            ),
            evaluated_at=now,
            intent=intent.model_copy(deep=True),
            limits=self._limits,
            approved_intent=approved_intent,
        )
        self._decisions.append(decision)
        return decision
