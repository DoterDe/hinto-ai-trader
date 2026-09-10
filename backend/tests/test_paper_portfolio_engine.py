import asyncio
import ast
from datetime import timedelta
from decimal import localcontext
from pathlib import Path

import pytest

from backtest_fixtures import START, bar, wave_bars
from src.application.backtest_engine import BacktestEngine
from src.application.paper_portfolio_engine import PaperPortfolioEngine
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.paper_portfolio import PaperPortfolioReport

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')


def multi_bars(count=80, symbols=SYMBOLS):
    sources = [wave_bars(count, symbol=symbol) for symbol in symbols]
    for group in zip(*sources):
        yield from group


@pytest.mark.asyncio
async def test_actual_pipeline_two_runs_are_identical_and_compete_for_capacity(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('network is forbidden')
    engine = PaperPortfolioEngine(symbols=SYMBOLS, settings=PaperPortfolioSettings(max_open_positions=1))
    # Restore before pytest-asyncio initializes Windows' internal loopback pair
    # during event-loop teardown. All portfolio work stays inside the guard.
    with monkeypatch.context() as network:
        network.setattr('socket.socket.connect', no_network)
        network.setattr('socket.create_connection', no_network)
        first, second = await engine.run(multi_bars()), await engine.run(multi_bars())
    assert first == second and first.model_dump_json() == second.model_dump_json()
    assert first.metadata.input_count == first.metrics.evaluated_decision_count == 240
    assert first.metadata.status == 'COMPLETE'
    assert first.metrics.upstream_eligible_count > first.metrics.reserved_count > 0
    assert first.metrics.rejected_count > 0 and first.metrics.completed_count > 0
    assert {item.symbol for item in first.reservations} == {'BTCUSDT'}
    assert first.metrics.max_simultaneous_open_positions == 1
    assert all(item.upstream.outcome == 'NO_ACTION' for item in first.decisions[:60])
    assert PaperPortfolioReport.model_validate_json(first.model_dump_json()) == first
    assert 'NaN' not in first.model_dump_json() and 'Infinity' not in first.model_dump_json()


@pytest.mark.asyncio
async def test_equal_time_multisymbol_permutations_have_identical_whole_reports():
    engine = PaperPortfolioEngine(symbols=SYMBOLS, settings=PaperPortfolioSettings(max_open_positions=1))
    original = await engine.run(multi_bars())
    for order in (tuple(reversed(SYMBOLS)), SYMBOLS[1:] + SYMBOLS[:1]):
        other = await engine.run(multi_bars(symbols=order))
        assert other.model_dump_json() == original.model_dump_json()


@pytest.mark.asyncio
async def test_future_prices_do_not_change_earlier_sizing_reservations_or_curve():
    data = list(multi_bars())
    changed = list(data)
    changed[70*3] = bar(70, opened='900', closed='910')
    engine = PaperPortfolioEngine(symbols=SYMBOLS)
    original, modified = await engine.run(data), await engine.run(changed)
    cutoff = START + timedelta(minutes=71)
    assert [item for item in original.decisions if item.evaluated_at < cutoff] == [item for item in modified.decisions if item.evaluated_at < cutoff]
    assert [item for item in original.reservations if item.decision_time < cutoff] == [item for item in modified.reservations if item.decision_time < cutoff]
    assert [item for item in original.curve if item.state.timestamp < cutoff] == [item for item in modified.curve if item.state.timestamp < cutoff]


@pytest.mark.asyncio
async def test_empty_and_short_no_eligible_runs():
    engine = PaperPortfolioEngine(symbols=SYMBOLS)
    empty = await engine.run(iter(()))
    assert empty.metadata.status == 'COMPLETE' and empty.final_state is None and empty.curve == ()
    assert empty.metrics.final_marked_equity == 100000 and empty.metadata.started_from is None
    short = await engine.run(multi_bars(3))
    assert short.metrics.upstream_no_action_count == 9 and short.positions == short.reservations == ()


@pytest.mark.asyncio
async def test_policy_and_data_change_identities_without_optimization():
    engine = PaperPortfolioEngine(symbols=SYMBOLS)
    first = await engine.run(multi_bars(3))
    other = await PaperPortfolioEngine(symbols=SYMBOLS, settings=PaperPortfolioSettings(max_open_positions=1)).run(multi_bars(3))
    assert first.metadata.portfolio_policy_id != other.metadata.portfolio_policy_id
    assert first.metadata.run_id != other.metadata.run_id and first.metadata.dataset_id == other.metadata.dataset_id
    altered = await engine.run([bar(i, closed='110') for i in range(3)])
    assert first.metadata.dataset_id != altered.metadata.dataset_id and first.metadata.run_id != altered.metadata.run_id


@pytest.mark.asyncio
async def test_phase6_signal_report_and_upstream_decisions_are_unchanged():
    backtest = BacktestEngine(symbols=('BTCUSDT',))
    before = await backtest.run(wave_bars())
    portfolio = await PaperPortfolioEngine(symbols=('BTCUSDT',)).run(wave_bars())
    after = await backtest.run(wave_bars())
    assert before.model_dump_json() == after.model_dump_json()
    assert [item.upstream for item in portfolio.decisions] == [item.decision for item in before.decisions]
    assert portfolio.metadata.dataset_id == before.metadata.dataset_id
    assert len(portfolio.positions) < len(before.outcomes)


@pytest.mark.asyncio
async def test_truncated_tail_exposes_incomplete_without_rewriting_prior_curve():
    engine = PaperPortfolioEngine(symbols=('BTCUSDT',))
    full = await engine.run(wave_bars())
    first_entry = full.reservations[0].expected_entry_time
    length = int((first_entry-START).total_seconds()/60)
    pending = await engine.run(wave_bars(length))
    assert pending.metadata.status == 'INCOMPLETE' and pending.positions == ()
    assert pending.metrics.missing_entry_reservation_count == 1
    opened = await engine.run(wave_bars(length+1))
    assert opened.metadata.status == 'INCOMPLETE' and opened.metrics.incomplete_count == 1
    assert opened.metrics.final_marked_equity is None
    assert opened.curve == full.curve[:len(opened.curve)]


@pytest.mark.asyncio
async def test_single_pass_long_replay_preserves_bounded_feature_history(monkeypatch):
    from src.application.feature_engine import FeatureEngine
    latest, sizes = FeatureEngine.latest, []
    def observed(self, symbol):
        snapshot = latest(self, symbol)
        sizes.append(snapshot.closed_candles)
        return snapshot
    monkeypatch.setattr(FeatureEngine, 'latest', observed)
    class SinglePass:
        used = False
        def __iter__(self):
            assert not self.used
            self.used = True
            yield from wave_bars(650)
    report = await PaperPortfolioEngine(symbols=('BTCUSDT',)).run(SinglePass())
    assert report.metadata.input_count == len(sizes) == 650 and max(sizes) == sizes[-1] == 500
    assert report.metrics.evaluated_decision_count == 650


@pytest.mark.asyncio
async def test_cancellation_and_source_errors_leave_no_tasks_or_subscribers(monkeypatch):
    from src.application.market_data_hub import MarketDataHub
    original, hubs = MarketDataHub.__init__, []
    def observed(self, *args, **kwargs):
        original(self, *args, **kwargs)
        hubs.append(self)
    monkeypatch.setattr(MarketDataHub, '__init__', observed)
    task = asyncio.create_task(PaperPortfolioEngine(symbols=SYMBOLS).run(multi_bars(10000)))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    def broken():
        yield bar()
        yield bar(1)
        raise ValueError('broken local input')
    with pytest.raises(ValueError, match='local input'):
        await PaperPortfolioEngine(symbols=SYMBOLS).run(broken())
    assert hubs and all(hub.status().subscriber_count == 0 for hub in hubs)
    assert not [task for task in asyncio.all_tasks() if task.get_name() == 'historical-feature-engine']


@pytest.mark.asyncio
async def test_ambient_decimal_context_does_not_change_report():
    engine, data = PaperPortfolioEngine(symbols=('BTCUSDT',)), tuple(wave_bars())
    first = await engine.run(data)
    with localcontext() as context:
        context.prec = 5
        second = await engine.run(data)
        assert context.prec == 5
    assert first.model_dump_json() == second.model_dump_json()


def test_scope_and_existing_openapi_remain_unchanged():
    from src.main import app
    assert len(app.openapi()['paths']) == 10
    assert all(set(item) == {'get'} for item in app.openapi()['paths'].values())
    root = Path(__file__).parents[1] / 'src'
    paths = list((root/'application').glob('paper_portfolio_*.py')) + [root/'domain'/'paper_portfolio.py']
    forbidden_names = {'TradeIntent', 'ApprovedTradeIntent', 'RiskEngine', 'PaperExecutionGateway', 'ExecutionGateway', 'OpenAI'}
    forbidden_modules = ('src.infrastructure', 'src.application.risk_engine', 'httpx', 'requests', 'websockets', 'openai',
                         'sqlite3', 'sqlalchemy', 'redis', 'optuna', 'sklearn', 'tensorflow', 'torch')
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_names, path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(forbidden_modules), path
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith(forbidden_modules) for item in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'now', 'utcnow', 'uuid4', 'submit_order', 'create_order', 'place_order'}, path


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,reason', [(0, 'missing_entry_bar'), (1, 'missing_horizon_bar')])
async def test_full_pipeline_missing_entry_or_holding_bar_remains_explicit(offset, reason):
    engine = PaperPortfolioEngine(symbols=('BTCUSDT',))
    original = await engine.run(wave_bars())
    entry_index = int((original.reservations[0].expected_entry_time-START).total_seconds()/60)
    damaged = [event for index, event in enumerate(wave_bars()) if index != entry_index+offset]
    report = await engine.run(damaged)
    assert report.metadata.status == 'INCOMPLETE'
    if offset == 0:
        assert report.expiries[0].reason == reason and not report.positions
    else:
        assert report.positions[0].reason == reason and not report.closes
        assert report.final_state.marked_equity is None and not report.metrics.valuation_complete
