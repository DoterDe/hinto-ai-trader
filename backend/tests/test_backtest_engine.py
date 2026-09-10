import asyncio
import ast
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from backtest_fixtures import START, bar, wave_bars
from src.application.backtest_engine import BacktestEngine
from src.application.backtest_settings import BacktestSettings
from src.application.decision_settings import DecisionSettings
from src.application.feature_settings import FeatureSettings
from src.application.strategy_settings import StrategySettings
from src.domain.backtesting import BacktestRunReport


@pytest.mark.asyncio
async def test_end_to_end_default_pipeline_report_is_byte_deterministic():
    engine = BacktestEngine(symbols=("BTCUSDT",))
    first, second = await engine.run(wave_bars()), await engine.run(wave_bars())
    assert first == second and first.model_dump_json() == second.model_dump_json()
    assert first.metadata.input_count == first.metrics.evaluated_decision_count == 80
    assert first.metadata.started_from == START and first.metadata.ended_at == START + timedelta(minutes=80)
    assert first.metrics.eligible_count > 0 and first.metrics.completed_count > 0
    assert len(first.outcomes) == first.metrics.eligible_count
    assert first.metrics.eligible_count + first.metrics.blocked_count + first.metrics.no_action_count == 80
    assert all(item.decision.outcome == "NO_ACTION" for item in first.decisions[:20])
    assert all(item.entry_time == item.decision_time for item in first.outcomes if item.entry_time is not None)
    assert all(item.regime is None for item in first.decisions[:20])
    assert any(item.regime is not None for item in first.decisions[50:])
    assert BacktestRunReport.model_validate_json(first.model_dump_json()) == first
    assert "NaN" not in first.model_dump_json() and "Infinity" not in first.model_dump_json()
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]


@pytest.mark.asyncio
async def test_empty_dataset_returns_explicit_empty_report():
    report = await BacktestEngine(symbols=("BTCUSDT",)).run(iter(()))
    assert report.metadata.input_count == 0
    assert report.metadata.started_from is report.metadata.ended_at is None
    assert report.decisions == report.outcomes == report.chronological_segments == ()
    assert report.metrics.completed_count == 0 and report.metrics.profit_factor is None


@pytest.mark.asyncio
async def test_dataset_and_each_settings_layer_changes_run_identity_without_optimization():
    original = await BacktestEngine(symbols=("BTCUSDT",)).run(wave_bars(4))
    variations = (
        dict(settings=BacktestSettings(holding_period_bars=1)),
        dict(settings=BacktestSettings(fee_bps_per_side=6)),
        dict(settings=BacktestSettings(chronological_segments=2)),
        dict(feature_settings=FeatureSettings(ema_long=51)),
        dict(strategy_settings=StrategySettings(candidate_score_threshold=41)),
        dict(decision_settings=DecisionSettings(min_contributing_strategies=3)),
    )
    for fixed in variations:
        changed = await BacktestEngine(symbols=("BTCUSDT",), **fixed).run(wave_bars(4))
        assert changed.metadata.dataset_id == original.metadata.dataset_id
        assert changed.metadata.run_id != original.metadata.run_id
    changed_data = await BacktestEngine(symbols=("BTCUSDT",)).run([bar(i, closed="110") for i in range(4)])
    assert changed_data.metadata.dataset_id != original.metadata.dataset_id
    assert changed_data.metadata.run_id != original.metadata.run_id


@pytest.mark.asyncio
async def test_cost_changes_never_change_the_production_decisions():
    low = await BacktestEngine(symbols=("BTCUSDT",), settings=BacktestSettings(fee_bps_per_side=0, slippage_bps_per_side=0)).run(wave_bars())
    high = await BacktestEngine(symbols=("BTCUSDT",), settings=BacktestSettings(fee_bps_per_side=20, slippage_bps_per_side=10)).run(wave_bars())
    assert low.decisions == high.decisions
    assert [item.returns.gross_return for item in low.outcomes] == [item.returns.gross_return for item in high.outcomes]
    assert high.metrics.sum_simulated_costs > low.metrics.sum_simulated_costs
    assert high.metrics.sum_net_returns < low.metrics.sum_net_returns


@pytest.mark.asyncio
async def test_short_dataset_tail_has_explicit_incomplete_outcomes():
    full = await BacktestEngine(symbols=("BTCUSDT",)).run(wave_bars())
    first = next(index for index, item in enumerate(full.decisions) if item.decision.outcome == "ELIGIBLE")
    truncated = await BacktestEngine(symbols=("BTCUSDT",)).run(wave_bars(first + 1))
    assert truncated.decisions == full.decisions[:first+1]
    assert truncated.metrics.incomplete_count >= 1
    assert truncated.outcomes[-1].reason == "missing_entry_bar"


@pytest.mark.asyncio
async def test_multi_symbol_reports_reconcile_with_canonical_order():
    data = [event for i in range(3) for event in (bar(i, symbol="ETHUSDT"), bar(i))]
    report = await BacktestEngine(symbols=("ETHUSDT", "BTCUSDT")).run(data)
    assert report.metadata.symbols == ("BTCUSDT", "ETHUSDT") and report.metadata.input_count == 6
    assert [item.metrics.evaluated_decision_count for item in report.per_symbol] == [3, 3]
    other = await BacktestEngine(symbols=("BTCUSDT", "ETHUSDT")).run(sorted(data, key=lambda b: (b.event_time, b.symbol)))
    assert report.model_dump_json() == other.model_dump_json()


@pytest.mark.asyncio
async def test_replay_ignores_ambient_decimal_precision_with_same_typed_input():
    bars = list(wave_bars())
    engine = BacktestEngine(symbols=("BTCUSDT",))
    first = await engine.run(bars)
    with localcontext() as context:
        context.prec = 7
        second = await engine.run(bars)
        assert context.prec == 7
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.asyncio
async def test_long_single_pass_replay_keeps_history_bounded_and_evaluates_once_per_bar(monkeypatch):
    from src.application.feature_engine import FeatureEngine
    original = FeatureEngine.latest
    history_sizes = []
    def inspect(self, symbol):
        result = original(self, symbol)
        history_sizes.append(result.closed_candles)
        return result
    monkeypatch.setattr(FeatureEngine, "latest", inspect)
    class SinglePass:
        used = False
        def __iter__(self):
            assert not self.used, "input iterator must not be replayed or copied in a second pass"
            self.used = True
            yield from wave_bars(650)
    report = await BacktestEngine(symbols=("BTCUSDT",)).run(SinglePass())
    assert report.metadata.input_count == len(history_sizes) == 650
    assert max(history_sizes) == 500 and history_sizes[-1] == 500
    assert report.metrics.evaluated_decision_count == 650


@pytest.mark.asyncio
async def test_cancellation_and_input_failure_clean_up_the_feature_subscription(monkeypatch):
    from src.application.market_data_hub import MarketDataHub
    original = MarketDataHub.__init__
    hubs = []
    def observe(self, *args, **kwargs):
        original(self, *args, **kwargs)
        hubs.append(self)
    monkeypatch.setattr(MarketDataHub, "__init__", observe)
    task = asyncio.create_task(BacktestEngine(symbols=("BTCUSDT",)).run(wave_bars(10000)))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hubs and all(hub.status().subscriber_count == 0 for hub in hubs)
    def broken():
        yield bar()
        yield bar(1)
        raise ValueError("invalid local dataset")
    with pytest.raises(ValueError, match="local dataset"):
        await BacktestEngine(symbols=("BTCUSDT",)).run(broken())
    assert all(hub.status().subscriber_count == 0 for hub in hubs)
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]


def test_scope_has_no_execution_private_network_or_optimizer_imports():
    root = Path(__file__).parents[1] / "src"
    paths = list((root / "application").glob("backtest_*.py")) + list((root / "application").glob("historical_*.py")) + [root / "domain" / "backtesting.py"]
    forbidden = {'TradeIntent', 'ApprovedTradeIntent', 'RiskEngine', 'PaperExecutionGateway',
                 'ExecutionGateway', 'BinancePublicMarketData', 'OpenAI'}
    forbidden_modules = ('src.infrastructure', 'src.application.risk_engine', 'openai', 'requests',
                         'httpx', 'websockets', 'redis', 'sqlite3', 'sqlalchemy', 'optuna', 'sklearn')
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden, path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(forbidden_modules), path
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(forbidden_modules) for alias in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'now', 'utcnow', 'uuid4', 'submit_order', 'create_order', 'place_order'}, path
