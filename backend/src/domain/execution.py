from __future__ import annotations

from typing import Protocol

from src.domain.models import ApprovedTradeIntent, ExecutionResult


class ExecutionGateway(Protocol):
    async def execute(
        self,
        intent: ApprovedTradeIntent,
        *,
        reference_price: float,
    ) -> ExecutionResult:
        ...
