"""Small explicitly synthetic offline export fixture, never market history."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.application.backtest_settings import BacktestSettings
from src.application.backtest_math import arithmetic
from src.application.historical_dataset import validate_historical_dataset
from src.application.validation_report import build_validation_report
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.market_data import KlineEvent
from src.domain.walk_forward import WalkForwardProtocol


@arithmetic
def example_dataset():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    previous = Decimal(100)
    for index in range(85):
        current = previous + (Decimal("2.4") if index >= 60 or index % 2 == 0 else Decimal("-2.4"))
        opening, end = start + timedelta(minutes=index), start + timedelta(minutes=index + 1)
        rows.append(KlineEvent(symbol="BTCUSDT", interval="1m", open_time=opening, close_time=end,
            event_time=end, received_at=end, open=previous, close=current,
            high=max(previous, current) + Decimal(".1"), low=min(previous, current) - Decimal(".1"),
            volume=10, quote_volume=current * 10, trade_count=index + 1, is_closed=True,
            taker_buy_volume=8, taker_buy_quote_volume=current * 8))
        previous = current
    return validate_historical_dataset(rows, symbols=("BTCUSDT",), source_label="synthetic-validation-example").require_dataset()


async def example_report(*, mode="EXPANDING"):
    data = example_dataset()
    protocol = WalkForwardProtocol(dataset_id=data.manifest.dataset_id, symbols=data.manifest.symbols,
                                    mode=mode, rolling_context_boundaries=50 if mode == "ROLLING" else None,
                                    test_boundaries=23, step_boundaries=23)
    costs = BacktestSettings(holding_period_bars=5, fee_bps_per_side=5, slippage_bps_per_side=2, chronological_segments=4)
    engine = WalkForwardEvaluator(protocol, backtest_settings=costs)
    return build_validation_report(data, await engine.run(data), costs)
