"""Bounded synthetic multi-symbol release evidence; no data downloads."""

from decimal import Decimal

from backtest_fixtures import bar
from src.application.backtest_math import arithmetic
from src.application.historical_dataset import validate_historical_dataset
from src.application.validation_report import build_validation_report
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.walk_forward import WalkForwardProtocol


@arithmetic
def medium_dataset():
    rows = []
    for symbol, initial in (("BTCUSDT", "100"), ("ETHUSDT", "1000")):
        previous = Decimal(initial)
        for index in range(280):
            if symbol == "BTCUSDT":
                change = (Decimal("2.4") if index % 2 == 0 else Decimal("-2.4")) if index < 60 else (
                    Decimal("2.4") if index < 140 else Decimal("-1.2") if index < 200 else Decimal(0))
                wick = Decimal(".1")
            else:
                change = Decimal("-1") if index < 200 else Decimal(0)
                wick = Decimal(20) if index < 110 else Decimal(".1")
            current = previous + change
            if not (symbol == "ETHUSDT" and index == 120):
                rows.append(bar(index, symbol=symbol, opened=str(previous), closed=str(current),
                                high=max(previous, current) + wick, low=min(previous, current) - wick))
            previous = current
    return validate_historical_dataset(rows, symbols=("BTCUSDT", "ETHUSDT"),
                                       source_label="synthetic-medium-release").require_dataset()


async def medium_report(data=None, *, mode="EXPANDING"):
    data = data or medium_dataset()
    protocol = WalkForwardProtocol(dataset_id=data.manifest.dataset_id, symbols=data.manifest.symbols,
        mode=mode, rolling_context_boundaries=50 if mode == "ROLLING" else None,
        # The first 23-bar test boundary cuts across known five-bar signal
        # horizons, exercising completed and censored evidence without retuning.
        test_boundaries=23, step_boundaries=23)
    engine = WalkForwardEvaluator(protocol)
    return build_validation_report(data, await engine.run(data), engine.backtest_settings)
