import ast
from pathlib import Path
from dataclasses import replace

import pytest

from backtest_fixtures import bar
from live_paper_fixtures import connect
from persistence_fixtures import admit, durable_runtime
from src.application.market_data_hub import ClosedBarObservation
from src.application.paper_persistence_codec import CheckpointCodec
from src.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['runtime', 'features', 'strategies', 'decisions', 'portfolio', 'costs', 'symbols', 'interval', 'freshness'])
async def test_every_required_configuration_identity_blocks_mixed_recovery(tmp_path, changed):
    from live_paper_fixtures import ManualLiveClock
    from src.application.live_paper_coordinator import LivePaperCoordinator
    from src.application.market_data_hub import MarketDataHub
    from src.application.paper_persistence_settings import PaperPersistenceSettings
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (base, hub, clock):
        await admit(base, hub, clock, [bar()])
        key = base.persistence.state.checkpoint_id
    clock = ManualLiveClock()
    clock.advance(bar().close_time)
    hub = MarketDataHub(('ETHUSDT',) if changed == 'symbols' else ('BTCUSDT',), clock=clock.now,
        kline_intervals=('5m',) if changed == 'interval' else ('1m',), stale_after_seconds=11 if changed == 'freshness' else 10)
    options = dict(settings=base.settings, feature_settings=base.feature_settings, strategy_settings=base.strategy_settings,
        decision_settings=base.decision_settings, portfolio_settings=base.portfolio_settings, costs=base.costs)
    fields = {'runtime': ('settings', 'event_history_limit', 16), 'features': ('feature_settings', 'ema_fast', 8),
        'strategies': ('strategy_settings', 'candidate_score_threshold', 41),
        'decisions': ('decision_settings', 'min_contributing_strategies', 3),
        'portfolio': ('portfolio_settings', 'max_open_positions', 3), 'costs': ('costs', 'fee_bps_per_side', 6)}
    if changed in fields:
        name, field, value = fields[changed]
        options[name] = options[name].__class__.model_validate(options[name].model_dump() | {field: value})
    runtime = LivePaperCoordinator(hub, clock=clock, persistence_settings=PaperPersistenceSettings(enabled=True, path=path), **options)
    try:
        assert not await runtime.persistence.start(runtime)
        assert runtime.persistence.state.status == 'INCOMPATIBLE'
        assert (await runtime.persistence._call(runtime.persistence.store.load)).checkpoint_id == key
        assert not runtime.running and runtime.analysis.task is None
    finally:
        await runtime.persistence.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('version', ['runtime_version', 'feature_version', 'strategy_version', 'decision_version', 'portfolio_version', 'backtest_version'])
async def test_analytical_version_changes_are_not_reinterpreted(tmp_path, monkeypatch, version):
    from src.application import paper_persistence as module
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (base, hub, clock):
        await admit(base, hub, clock, [bar()])
    original = module.compatibility
    monkeypatch.setattr(module, 'compatibility', lambda runtime: original(runtime).model_copy(update={version: 'future-version'}))
    with pytest.raises(AssertionError, match='INCOMPATIBLE'):
        async with durable_runtime(path, start_at=bar().close_time):
            raise AssertionError('incompatible recovery was allowed')


@pytest.mark.asyncio
async def test_recovered_partial_group_cannot_mix_transport_generations(tmp_path):
    path = tmp_path / 'paper.db'
    symbols = ('BTCUSDT', 'ETHUSDT')
    async with durable_runtime(path, symbols=symbols) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar(symbol=s) for s in symbols])
    async with durable_runtime(path, symbols=symbols, start_at=bar().close_time) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar(1)])
        assert runtime.batcher.pending_count == 1
        connect(hub, clock, generation=2)
        event = bar(1, symbol='ETHUSDT')
        hub.publish(event, connection_id='injected_public')
        await runtime.accept(ClosedBarObservation(bar=event, connection_id='injected_public', generation=2))
        assert len(runtime.decisions) == 2
        assert runtime.portfolio.last_boundary == bar().close_time
        assert runtime.batcher.pending_count == 0
        assert runtime.batcher.watermark == bar(1).close_time


@pytest.mark.asyncio
async def test_rotation_during_continuity_fence_write_rechecks_source(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        connect(hub, clock, generation=2)
        original = runtime.persistence._call
        rotated = False
        async def change(function, *args, **kwargs):
            nonlocal rotated
            value = await original(function, *args, **kwargs)
            if function == runtime.persistence.store.save_fence and not rotated:
                connect(hub, clock, generation=3)
                rotated = True
            return value
        runtime.persistence._call = change
        clock.advance(bar(1).close_time)
        await runtime.accept(ClosedBarObservation(bar=bar(1), connection_id='injected_public', generation=2))
        assert rotated and runtime.counts['obsolete_generation'] == 1
        assert len(runtime.decisions) == 1 and runtime.portfolio.last_boundary == bar().close_time


@pytest.mark.asyncio
async def test_failed_fence_keeps_previous_durable_state_and_halts(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        previous = runtime.persistence.state.checkpoint_id
        runtime.persistence.store.fault = lambda stage: (_ for _ in ()).throw(OSError('disk')) if stage == 'before_fence_commit' else None
        connect(hub, clock, generation=2)
        with pytest.raises(OSError):
            await runtime.poll()
        assert runtime.persistence.halted and runtime.persistence.state.status == 'DEGRADED'
        assert (await runtime.persistence._call(runtime.persistence.store.load)).checkpoint_id == previous
        assert await runtime.persistence._call(runtime.persistence.store.load_fence) is None
        with pytest.raises(RuntimeError, match='halted'):
            await admit(runtime, hub, clock, [bar(1)])
        assert runtime.portfolio.last_boundary == bar().close_time


def test_phase9_openapi_is_get_only_and_contains_no_execution_contract():
    schema = create_app().openapi()
    assert len(schema['paths']) == 19
    for path, operations in schema['paths'].items():
        assert set(operations) == {'get'}, path
    forbidden = {'TradeIntent', 'ApprovedTradeIntent', 'ExecutionResult', 'RiskLimits', 'AIDecision'}
    assert not forbidden.intersection(schema['components']['schemas'])
    assert 'PersistenceSnapshot' in schema['components']['schemas']


def test_phase9_source_has_no_prohibited_integrations():
    root = Path(__file__).resolve().parents[1] / 'src'
    paths = list((root / 'application').glob('paper_persist*.py')) + [root / 'application' / 'paper_recovery_state.py',
        root / 'application' / 'paper_position_evidence.py', root / 'domain' / 'paper_persistence.py',
        root / 'infrastructure' / 'sqlite_paper_store.py']
    forbidden = {'TradeIntent', 'ApprovedTradeIntent', 'RiskEngine', 'PaperExecutionGateway', 'OpenAI'}
    modules = ('openai', 'httpx', 'requests', 'websockets', 'redis', 'sqlalchemy', 'optuna', 'sklearn', 'torch', 'tensorflow')
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden, path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(modules), path
            if isinstance(node, ast.Import):
                assert not any(n.name.startswith(modules) for n in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'submit_order', 'create_order', 'place_order', 'transfer', 'withdraw', 'deposit'}, path
