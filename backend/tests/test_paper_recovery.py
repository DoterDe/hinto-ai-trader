import asyncio
import sqlite3
from datetime import timedelta

import pytest

from backtest_fixtures import bar, wave_bars
from live_paper_fixtures import ManualLiveClock, connect
from persistence_fixtures import admit, durable_runtime
from src.application.feature_settings import FeatureSettings
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.market_data_hub import MarketDataHub
from src.application.paper_persistence_codec import CheckpointCodec
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.application.paper_recovery_state import capture
from src.domain.market_data import ConnectionStatus


def authoritative(runtime):
    checkpoint = capture(runtime, runtime.persistence.state.session_id, runtime.persistence.state.session_created_at)
    # Runtime start/stop, receipt-token labels and event counters are diagnostic.
    # Analytical/portfolio identities, history/reset provenance and accounting are not.
    return {'ledger': checkpoint.ledger.model_dump_json(), 'batcher': checkpoint.batcher.model_dump_json(),
        'state': runtime.portfolio.state(checkpoint.durable_boundary).model_dump_json(),
        'analysis': checkpoint.analysis.model_dump_json() if checkpoint.analysis else None,
        'decisions': [a.portfolio.model_dump_json() for a in checkpoint.decisions],
        'generation': checkpoint.generation, 'boundary': checkpoint.durable_boundary}


@pytest.mark.asyncio
@pytest.mark.parametrize('cuts', [(1,), (50,), (51,), (55,), (10, 30, 50, 51, 55, 70)])
async def test_restart_matches_uninterrupted_entire_authoritative_state(tmp_path, cuts):
    candles = list(wave_bars())
    async with durable_runtime(tmp_path / 'reference.db') as (runtime, hub, clock):
        for candle in candles:
            await admit(runtime, hub, clock, [candle])
        expected = authoritative(runtime)
        assert runtime.portfolio.completed_count > 0
    session = None
    start = 0
    for end in (*cuts, len(candles)):
        async with durable_runtime(tmp_path / 'restart.db', start_at=candles[start-1].close_time if start else None) as (runtime, hub, clock):
            if start:
                assert runtime.persistence.state.status == 'RECOVERED'
                assert runtime.persistence.state.session_id == session
                previous = runtime.persistence.state.checkpoint_id
                # Repeated last close never evaluates or accounts twice.
                await admit(runtime, hub, clock, [candles[start-1]])
                assert runtime.persistence.state.checkpoint_id == previous
            else:
                session = runtime.persistence.state.session_id
            for candle in candles[start:end]:
                await admit(runtime, hub, clock, [candle])
            actual = authoritative(runtime)
        start = end
    assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['reservation', 'active', 'incomplete'])
async def test_exact_restoration_and_missing_downtime_bar_stays_missing(tmp_path, state):
    candles = list(wave_bars())
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (runtime, hub, clock):
        for index, candle in enumerate(candles):
            await admit(runtime, hub, clock, [candle])
            if runtime.portfolio.pending:
                break
        if state != 'reservation':
            index += 1
            await admit(runtime, hub, clock, [candles[index]])
            assert runtime.portfolio.active
        if state == 'incomplete':
            index += 2
            await admit(runtime, hub, clock, [candles[index]])
            assert runtime.portfolio.state(clock.now()).marked_equity is None
        saved = authoritative(runtime)
    async with durable_runtime(path, start_at=candles[index].close_time) as (runtime, hub, clock):
        assert authoritative(runtime) == saved
        assert hub.latest('BTCUSDT').events == {}  # recovered evidence is not a fresh public price
        await admit(runtime, hub, clock, [candles[index+2]])
        assert not runtime.portfolio.pending
        if state == 'reservation':
            assert runtime.portfolio.expired_count >= 1
        else:
            assert runtime.portfolio.positions()[0].position.status == 'INCOMPLETE'
            assert runtime.portfolio.state(clock.now()).marked_equity is None


@pytest.mark.asyncio
async def test_conflicting_duplicate_persists_loss_fence_without_rewriting_checkpoint(tmp_path):
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (runtime, hub, clock):
        for candle in wave_bars():
            await admit(runtime, hub, clock, [candle])
            if runtime.portfolio.active:
                break
        checkpoint_id = runtime.persistence.state.checkpoint_id
        held_boundary = runtime.portfolio.last_boundary
        changed = candle.model_copy(update={'close': candle.close + 1, 'high': candle.high + 1})
        await admit(runtime, hub, clock, [changed])
        assert runtime.persistence.state.checkpoint_id == checkpoint_id
        assert runtime.portfolio.positions()[0].position.status == 'INCOMPLETE'
    async with durable_runtime(path, start_at=held_boundary) as (runtime, hub, clock):
        assert runtime.persistence.state.reason == 'recovered_continuity_loss'
        assert runtime.persistence.state.checkpoint_id == checkpoint_id
        assert runtime.portfolio.positions()[0].position.status == 'INCOMPLETE'
        assert runtime.portfolio.state(clock.now()).marked_equity is None


@pytest.mark.asyncio
async def test_restart_transport_bootstrap_preserves_history_but_next_disconnect_invalidates(tmp_path):
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        generation = runtime._generation
    async with durable_runtime(path, start_at=bar().close_time) as (runtime, hub, clock):
        connect(hub, clock, generation=1, status=ConnectionStatus.CONNECTING)
        await runtime.poll()
        assert runtime._generation == generation
        connect(hub, clock, generation=1)
        await admit(runtime, hub, clock, [bar(1)])
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 2
        connect(hub, clock, generation=2, status=ConnectionStatus.RECONNECTING)
        await runtime.poll()
        assert runtime._generation == generation + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation,expected', [('config', 'INCOMPATIBLE'), ('checksum', 'CORRUPT'),
    ('schema', 'INCOMPATIBLE'), ('fence', 'CORRUPT'), ('clock', 'INCOMPATIBLE')])
async def test_recovery_fail_closed_without_new_session(tmp_path, mutation, expected):
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
    with sqlite3.connect(path) as conn:
        if mutation == 'checksum':
            conn.execute("UPDATE paper_checkpoints SET checksum='broken'")
        if mutation == 'schema':
            conn.execute('UPDATE schema_metadata SET version=99')
        if mutation == 'fence':
            conn.execute("UPDATE paper_sessions SET continuity_fence='broken'")
    clock = ManualLiveClock()
    if mutation != 'clock':
        clock.advance(bar().close_time)
    hub = MarketDataHub(('BTCUSDT',), clock=clock.now)
    config = LivePaperSettings(enabled=True, event_history_limit=15, curve_history_limit=20, position_history_limit=10)
    runtime = LivePaperCoordinator(hub, clock=clock, settings=config,
        feature_settings=FeatureSettings(ema_fast=8) if mutation == 'config' else None,
        persistence_settings=PaperPersistenceSettings(enabled=True, path=path))
    await runtime.run()
    assert runtime.persistence.state.status == expected and runtime.health()[0] == 'ERROR'
    assert not runtime.running and runtime.persistence.halted and runtime.persistence.worker is None
    assert hub.status().subscriber_count == 0
    assert runtime.persistence.state.session_id is None
    assert runtime.portfolio.state(clock.now()).marked_equity is None


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['before_commit', 'after_commit'])
async def test_process_restart_between_transition_commit_and_publication(tmp_path, stage):
    path = tmp_path / 'paper.db'
    async with durable_runtime(path) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        before = runtime.persistence.state.checkpoint_id
        runtime.persistence.store.fault = lambda point: (_ for _ in ()).throw(OSError('crash')) if point == stage else None
        with pytest.raises(OSError):
            await admit(runtime, hub, clock, [bar(1)])
        assert runtime.persistence.state.checkpoint_id == before
    async with durable_runtime(path, start_at=bar(1).close_time) as (runtime, hub, clock):
        assert runtime.portfolio.last_boundary == bar(1 if stage == 'after_commit' else 0).close_time
        if stage == 'before_commit':
            await admit(runtime, hub, clock, [bar(1)])
        assert runtime.counts['finalized_batches'] == 2
        assert len(runtime.decisions) == 2


@pytest.mark.asyncio
async def test_equal_time_symbol_permutation_across_restart_preserves_arbitration(tmp_path):
    from src.application.paper_portfolio_settings import PaperPortfolioSettings
    symbols = ('BTCUSDT', 'ETHUSDT')
    data = {symbol: list(wave_bars(symbol=symbol)) for symbol in symbols}
    expected = None
    for name, cuts, order in [('reference', (80,), symbols), ('restarted', (50, 80), tuple(reversed(symbols)))]:
        start = 0
        identities = []
        for end in cuts:
            async with durable_runtime(tmp_path / (name + '.db'), symbols=symbols,
                start_at=data[symbols[0]][start-1].close_time if start else None,
                portfolio_settings=PaperPortfolioSettings(max_open_positions=1)) as (runtime, hub, clock):
                for index in range(start, end):
                    await admit(runtime, hub, clock, [data[s][index] for s in order])
                    identities.extend(a.portfolio.model_dump_json() for a in runtime.decisions if a.boundary == data[symbols[0]][index].close_time)
                result = authoritative(runtime), identities
                assert runtime.portfolio.completed_count > 0 or end < 60
            start = end
        if expected is None:
            expected = result
        else:
            assert result == expected
