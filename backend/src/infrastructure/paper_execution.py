from __future__ import annotations

from math import isfinite
from threading import Lock
from uuid import uuid4

from src.domain.models import ApprovedTradeIntent, ExecutionResult, TradingMode


class PaperExecutionGateway:
    """In-memory simulated execution gateway.

    The supplied reference price is treated as the fill price. Slippage,
    commissions, and persistence will be added in later phases.

    A signal ID can produce only one fill per gateway instance. Retrying the
    same approved payload returns that original fill, even if the reference
    price has moved. A different payload using the same ID is rejected.
    """

    def __init__(self) -> None:
        self._fills: list[ExecutionResult] = []
        self._executions: dict[str, tuple[ApprovedTradeIntent, ExecutionResult]] = {}
        self._lock = Lock()

    @property
    def fills(self) -> tuple[ExecutionResult, ...]:
        with self._lock:
            return tuple(self._fills)

    async def execute(
        self,
        intent: ApprovedTradeIntent,
        *,
        reference_price: float,
    ) -> ExecutionResult:
        if not isinstance(intent, ApprovedTradeIntent):
            raise TypeError("paper execution requires an ApprovedTradeIntent")
        approved = ApprovedTradeIntent.model_validate(intent)

        try:
            valid_price = (
                not isinstance(reference_price, bool)
                and isfinite(reference_price)
                and reference_price > 0
            )
        except (TypeError, ValueError, OverflowError):
            valid_price = False
        if not valid_price:
            raise ValueError("reference_price must be finite and positive")

        with self._lock:
            existing = self._executions.get(approved.signal_id)
            if existing is not None:
                existing_intent, existing_result = existing
                if approved != existing_intent:
                    raise ValueError("signal_id already executed with a different approved intent")
                return existing_result

            result = ExecutionResult(
                execution_id=str(uuid4()),
                signal_id=approved.signal_id,
                symbol=approved.symbol,
                side=approved.side,
                quantity=approved.quantity,
                fill_price=reference_price,
                mode=TradingMode.PAPER,
            )
            self._executions[approved.signal_id] = (approved, result)
            self._fills.append(result)
            return result
