import pytest

from src.domain.models import ApprovedTradeIntent, SignalSide
from src.infrastructure.paper_execution import PaperExecutionGateway


@pytest.mark.asyncio
async def test_paper_execution_records_fill() -> None:
    gateway = PaperExecutionGateway()
    intent = ApprovedTradeIntent(
        signal_id="sig-paper-1",
        symbol="BTCUSDT",
        side=SignalSide.LONG,
        quantity=0.1,
    )

    result = await gateway.execute(intent, reference_price=100_000.0)

    assert result.mode.value == "paper"
    assert result.fill_price == 100_000.0
    assert result.signal_id == "sig-paper-1"
    assert len(gateway.fills) == 1


@pytest.mark.asyncio
async def test_paper_execution_rejects_invalid_price() -> None:
    gateway = PaperExecutionGateway()
    intent = ApprovedTradeIntent(
        signal_id="sig-paper-2",
        symbol="ETHUSDT",
        side=SignalSide.SHORT,
        quantity=0.2,
    )

    with pytest.raises(ValueError):
        await gateway.execute(intent, reference_price=0)
