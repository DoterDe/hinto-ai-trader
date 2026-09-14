import asyncio
import sqlite3
import threading

import pytest

from backtest_fixtures import bar, wave_bars
from live_paper_fixtures import ManualLiveClock
from test_live_paper_lifecycle import InjectedPublicSource
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.application.paper_recovery_state import capture
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 15)


@pytest.mark.asyncio
async def test_enabled_offline_lifespan_recovers_before_source_and_stops_all_workers(tmp_path):
    path = tmp_path / 'paper.db'
    identity = None
    for index in range(3):
        clock = ManualLiveClock()
        if index:
            clock.advance(bar(index-1).close_time)
        class CheckedSource(InjectedPublicSource):
            async def run(self, sink):
                state = app.state.live_paper_coordinator.persistence.state
                assert state.status == ('RECOVERED' if index else 'NEW_SESSION')
                assert app.state.live_paper_coordinator.running
                await super().run(sink)
        source = CheckedSource(clock)
        app = create_app(settings=MarketDataSettings(enabled=False, symbols=('BTCUSDT',)), source=source, clock=clock,
            live_paper_settings=LivePaperSettings(enabled=True),
            persistence_settings=PaperPersistenceSettings(enabled=True, path=path))
        async with app.router.lifespan_context(app):
            runtime = app.state.live_paper_coordinator
            assert source.started
            if identity:
                assert runtime.persistence.state.session_id == identity
            identity = runtime.persistence.state.session_id
            clock.advance(bar(index).close_time)
            source.input.put_nowait([bar(index)])
            await wait_until(lambda: runtime.persistence.state.durable_boundary == bar(index).close_time or not runtime.running)
            assert runtime.running
            assert len(runtime.decisions) == index + 1
        assert source.stopped and not runtime.running
        assert runtime.persistence.worker is None and app.state.market_data_hub.status().subscriber_count == 0
        assert runtime.analysis.hub.status().subscriber_count == 0
        assert not clock.waiters
        assert not [t for t in threading.enumerate() if t.name.startswith('paper-store')]
        assert not [t for t in asyncio.all_tasks() if t.get_name().startswith('live-paper-')]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['schema', 'corrupt'])
async def test_failed_recovery_never_starts_public_producer(tmp_path, failure):
    path = tmp_path / 'paper.db'
    if failure == 'schema':
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE schema_metadata(version INTEGER)')
            conn.execute('INSERT INTO schema_metadata VALUES(99)')
    else:
        path.write_bytes(b'corrupt database')
    clock = ManualLiveClock()
    source = InjectedPublicSource(clock)
    app = create_app(settings=MarketDataSettings(enabled=False), source=source, clock=clock,
        live_paper_settings=LivePaperSettings(enabled=True),
        persistence_settings=PaperPersistenceSettings(enabled=True, path=path))
    async with app.router.lifespan_context(app):
        assert not source.started and app.state.live_paper_task is None and app.state.market_data_task is None
        runtime = app.state.live_paper_coordinator
        assert runtime.health()[0] == 'ERROR'
        assert runtime.persistence.state.status == ('INCOMPATIBLE' if failure == 'schema' else 'CORRUPT')
    assert runtime.persistence.worker is None
    assert app.state.market_data_hub.status().subscriber_count == 0


@pytest.mark.asyncio
async def test_disabled_persistence_opens_no_file_or_worker(tmp_path):
    path = tmp_path / 'paper.db'
    clock = ManualLiveClock()
    source = InjectedPublicSource(clock)
    app = create_app(settings=MarketDataSettings(enabled=False), source=source, clock=clock,
        live_paper_settings=LivePaperSettings(enabled=True),
        persistence_settings=PaperPersistenceSettings(enabled=False, path=path))
    async with app.router.lifespan_context(app):
        assert app.state.live_paper_coordinator.persistence.state.status == 'DISABLED'
        assert app.state.live_paper_coordinator.running
    assert not path.exists()


@pytest.mark.asyncio
async def test_clean_lifespan_stop_preserves_open_exposure_exactly(tmp_path):
    clock = ManualLiveClock()
    path = tmp_path / 'paper.db'
    source = InjectedPublicSource(clock)
    def application(feed):
        return create_app(settings=MarketDataSettings(enabled=False, symbols=('BTCUSDT',)), source=feed, clock=clock,
            live_paper_settings=LivePaperSettings(enabled=True, event_history_limit=5, curve_history_limit=7),
            persistence_settings=PaperPersistenceSettings(enabled=True, path=path, checkpoint_history=2))
    app = application(source)
    async with app.router.lifespan_context(app):
        runtime = app.state.live_paper_coordinator
        for event in wave_bars():
            clock.advance(event.close_time)
            source.input.put_nowait([event])
            await wait_until(lambda: runtime.persistence.state.durable_boundary == event.close_time or not runtime.running)
            assert runtime.running
            if runtime.portfolio.active:
                break
        assert runtime.portfolio.active
        before = capture(runtime, runtime.persistence.state.session_id, runtime.persistence.state.session_created_at).ledger
        key = runtime.persistence.state.checkpoint_id
    assert all(p.status == 'OPEN' for p in runtime.portfolio.active.values())
    assert runtime.persistence.state.checkpoint_id == key
    restarted_source = InjectedPublicSource(clock)
    app = application(restarted_source)
    async with app.router.lifespan_context(app):
        recovered = app.state.live_paper_coordinator
        after = capture(recovered, recovered.persistence.state.session_id, recovered.persistence.state.session_created_at).ledger
        assert after == before and recovered.persistence.state.checkpoint_id == key
        assert recovered.portfolio.state(clock.now()).marked_equity is not None
        # An actual analytical failure is a different event from clean shutdown.
        def fail(*args, **kwargs):
            raise RuntimeError('injected analytical failure')
        recovered.analysis.evaluate = fail
        next_bar = bar(event.trade_count)
        clock.advance(next_bar.close_time)
        restarted_source.input.put_nowait([next_bar])
        await wait_until(lambda: not recovered.running)
        assert recovered.health()[0] == 'ERROR'
        assert recovered.persistence.state.reason == 'continuity_loss_saved'
    app = application(InjectedPublicSource(clock))
    async with app.router.lifespan_context(app):
        failed = app.state.live_paper_coordinator
        assert failed.persistence.state.reason == 'recovered_continuity_loss'
        assert all(p.status == 'INCOMPLETE' for p in failed.portfolio.active.values())
        assert failed.portfolio.state(clock.now()).marked_equity is None
