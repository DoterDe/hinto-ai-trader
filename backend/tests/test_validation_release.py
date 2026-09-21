import socket
from decimal import Decimal
from time import perf_counter

import httpx
import pytest

from test_walk_forward_evaluator import capture_frames, local_window
from validation_release_fixture import medium_dataset, medium_report
from src.application.historical_dataset import validate_historical_dataset
from src.application.validation_costs import fixed_cost_scenarios, recost_outcomes
from src.application.validation_report_codec import ValidationReportCodec
from src.application.validation_telemetry import project_validation
from src.application.backtest_settings import BacktestSettings
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["EXPANDING", "ROLLING"])
async def test_medium_offline_path_repeats_all_identities_and_bytes(mode, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("release validation must remain offline")
    data = medium_dataset()
    reversed_data = validate_historical_dataset(reversed(data.bars), symbols=tuple(reversed(data.manifest.symbols)),
        source_label=data.manifest.source_label).require_dataset()
    # Limit the network barrier to the real validation path; pytest's Windows
    # event-loop teardown legitimately creates its own local socket pair.
    with monkeypatch.context() as patch:
        patch.setattr(socket.socket, "connect", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        started = perf_counter()
        first = await medium_report(data, mode=mode)
        first_runtime = perf_counter() - started
        second = await medium_report(reversed_data, mode=mode)
    left, right = ValidationReportCodec.encode(first), ValidationReportCodec.encode(second)
    assert left == right  # Includes every identity, decision, assignment, cost and metric.
    assert data.manifest.dataset_id == reversed_data.manifest.dataset_id
    assert first.evaluation == second.evaluation and first.report_id == second.report_id
    assert first.dataset.total_bars == 559 and first.dataset.missing_bar_count == 1
    assert len(first.windows) == 10
    assert first.aggregate.metrics.completed_count > 0 and first.aggregate.metrics.incomplete_count > 0
    assert any(window.metrics is not None and window.metrics.eligible_count == 0 for window in first.evaluation.windows)
    assert any(window.status == "INSUFFICIENT_CONTEXT" for window in first.evaluation.windows)
    regimes = [e.regime for window in first.evaluation.windows for e in window.evidence]
    assert {item.trend for item in regimes} >= {"UPTREND", "DOWNTREND", "RANGE"}
    assert {item.volatility for item in regimes} >= {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
    assert len(first.aggregate.costs) == 4
    assert "VALID_WITH_GAPS" in first.warnings
    snapshot = project_validation(first)
    app = create_app(settings=MarketDataSettings(enabled=False))
    app.state.validation_snapshot = snapshot
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        assert (await client.get("/validation/latest")).json() == snapshot.model_dump(mode="json")
    print(f"\nmedium {mode}: {first_runtime:.3f}s first replay/report, {len(left)} canonical bytes, "
          f"{first.report_id}, dataset={data.manifest.dataset_id}, protocol={first.evaluation.plan.protocol_id}")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["EXPANDING", "ROLLING"])
async def test_release_future_mutation_preserves_full_earlier_frames_and_window_analyses(mode, monkeypatch):
    runs = capture_frames(monkeypatch)
    data = medium_dataset()
    first = await medium_report(data, mode=mode)
    earlier_frames = list(runs)
    runs.clear()
    row = next(row for row in data.bars if row.symbol == "BTCUSDT" and row.trade_count == 231)
    mutated = row.model_copy(update={"close": row.close + 100, "high": row.high + 200, "quote_volume": (row.close + 100) * 10})
    changed = validate_historical_dataset((mutated if b == row else b for b in data.bars),
        symbols=data.manifest.symbols, source_label=data.manifest.source_label).require_dataset()
    second = await medium_report(changed, mode=mode)
    assert first.report_id != second.report_id
    # First two windows end before the future mutation and include completed horizons.
    assert first.evaluation.windows[0].metrics.completed_count > 0
    for index in (0, 1):
        assert local_window(first.evaluation.windows[index]) == local_window(second.evaluation.windows[index])
        assert first.windows[index] == second.windows[index]
        assert earlier_frames[index] == runs[index]  # Actual feature + strategy snapshots, not only hashes.
    mutated_window = next(index for index, window in enumerate(first.evaluation.windows)
                          if window.split.test_start <= row.open_time < window.split.test_end)
    assert first.evaluation.windows[mutated_window].result_id != second.evaluation.windows[mutated_window].result_id
    assert [w.split.split_id for w in first.evaluation.windows] == [w.split.split_id for w in second.evaluation.windows]
    # Cost analysis cannot alter any captured analytical evidence or boundary.
    window = first.evaluation.windows[0]
    before = window.model_dump_json()
    costs = BacktestSettings(**first.cost_baseline.model_dump())
    previous = None
    for scenario in fixed_cost_scenarios(costs):
        outcomes = recost_outcomes(window.outcomes, costs, scenario)
        assert [(o.decision_id, o.entry_time, o.exit_time) for o in outcomes] == [(o.decision_id, o.entry_time, o.exit_time) for o in window.outcomes]
        returns = [o.returns.net_return for o in outcomes if o.returns is not None]
        if previous is not None: assert all(later <= earlier for later, earlier in zip(returns, previous))
        else: assert returns == [o.returns.gross_return for o in window.outcomes if o.returns is not None]
        previous = returns
    assert window.model_dump_json() == before
