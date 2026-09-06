from __future__ import annotations

from uuid import uuid4

from src.domain.models import ApprovedTradeIntent, ExecutionResult, TradingMode


class PaperExecutionGateway:
    """In-memory simulated execution gateway.

    The supplied reference price is treated as the fill price. Slippage,
    commissions, and persistence will be added in later phases.
    """

    def __init__(self) -> None:
        self._fills: list[ExecutionResult] = []

    @property
    def fills(self) -> tuple[ExecutionResult, ...]:
        return tuple(self._fills)

    async def execute(
        self,
        intent: ApprovedTradeIntent,
        *,
        reference_price: float,
    ) -> ExecutionResult:
        if reference_price <= 0:
            raise ValueError("reference_price must be positive")

        result = ExecutionResult(
            execution_id=str(uuid4()),
            signal_id=intent.signal_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            fill_price=reference_price,
            mode=TradingMode.PAPER,
        )
        self._fills.append(result)
        return result
