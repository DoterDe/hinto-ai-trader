import asyncio
from datetime import timedelta

import pytest

from backtest_fixtures import bar, wave_bars
from live_paper_fixtures import ManualLiveClock, checkpoint, connect, publish_group, running
from src.application.live_paper_settings import LivePaperSettings
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app


class InjectedPublicSource:
    def __init__(self, clock):
        self.clock = clock
        self.input = asyncio.Queue()
        self.started = self.stopped = False

    async def run(self, sink):
        connect(sink, self.clock)
        self.started = True
        try:
            while True:
                events = await self.input.get()
                for event in events:
                    sink.publish(event, connection_id='injected_public')
                self.input.task_done()
        finally:
            self.stopped = True


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_disabled_feed_without_source_needs_no_paper_or_feature_task(enabled):
    clock = ManualLiveClock()
    app = create_app(settings=MarketDataSettings(enabled=False), clock=clock,
                     live_paper_settings=LivePaperSettings(enabled=enabled))
    async with app.router.lifespan_context(app):
        assert app.state.live_paper_task is None
        assert app.state.feature_engine_task is None
        assert app.state.live_paper_coordinator.health()[0] == 'DISABLED'
        assert app.state.market_data_hub.status().subscriber_count == 0
    assert app.state.market_data_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_injected_source_lifespan_enabled_once_and_cleans_up(enabled):
    clock = ManualLiveClock()
    source = InjectedPublicSource(clock)
    app = create_app(settings=MarketDataSettings(enabled=False, symbols=('BTCUSDT',)), source=source,
                     clock=clock, live_paper_settings=LivePaperSettings(enabled=enabled))
    async with app.router.lifespan_context(app):
        assert source.started
        assert app.state.market_data_hub.status().subscriber_count == (2 if enabled else 1)
        for index in range(3):
            event = bar(index)
            clock.advance(event.received_at)
            source.input.put_nowait([event])
            await source.input.join()
            if enabled:
                await checkpoint(lambda: app.state.live_paper_coordinator.counts['finalized_batches'] == index+1)
        if enabled:
            runtime = app.state.live_paper_coordinator
            assert runtime.analysis.features.running and len(runtime.decisions) == 3
            assert len([task for task in asyncio.all_tasks() if task.get_name() == 'live-paper-coordinator']) == 1
        else:
            assert app.state.live_paper_task is None
    assert source.stopped and app.state.market_data_task.done()
    assert app.state.market_data_hub.status().subscriber_count == 0
    assert not app.state.feature_engine.running
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith('live-paper-')]
    assert not clock.waiters


@pytest.mark.asyncio
async def test_generation_change_during_analytical_startup_cannot_admit_old_batch(monkeypatch):
    async with running() as (runtime, hub, clock):
        original = runtime.analysis.start
        async def changed(boundary):
            await original(boundary)
            connect(hub, clock, generation=2)
        monkeypatch.setattr(runtime.analysis, 'start', changed)
        await publish_group(runtime, hub, clock, [bar()])
        assert runtime.counts['generation_changed_during_batch'] == 1
        assert not runtime.decisions


@pytest.mark.asyncio
async def test_age_rechecked_after_analytical_startup_yield(monkeypatch):
    async with running() as (runtime, hub, clock):
        original = runtime.analysis.start
        async def delayed(boundary):
            await original(boundary)
            clock.advance(seconds=10)
        monkeypatch.setattr(runtime.analysis, 'start', delayed)
        await publish_group(runtime, hub, clock, [bar()])
        assert runtime.counts['stale_finalized_bar'] == 1
        assert not runtime.decisions


@pytest.mark.asyncio
async def test_cancellation_during_lazy_analytical_startup_removes_nested_task(monkeypatch):
    async with running() as (runtime, hub, clock):
        original = runtime.analysis.start
        entered = asyncio.Event()
        async def held(boundary):
            await original(boundary)
            entered.set()
            await asyncio.Future()
        monkeypatch.setattr(runtime.analysis, 'start', held)
        clock.advance(bar().received_at)
        hub.publish(bar(), connection_id='injected_public')
        await entered.wait()
    assert not runtime.analysis.features.running


@pytest.mark.asyncio
@pytest.mark.parametrize('open_position', [False, True])
async def test_silent_source_expires_entry_or_marks_holding_unknown(open_position):
    async with running() as (runtime, hub, clock):
        data = list(wave_bars())
        for index, event in enumerate(data):
            await publish_group(runtime, hub, clock, [event])
            if runtime.portfolio.pending:
                break
        assert runtime.portfolio.pending
        if open_position:
            await publish_group(runtime, hub, clock, [data[index+1]])
            assert runtime.portfolio.active
        prior = tuple(point.model_dump_json() for point in runtime.portfolio.curve)
        due = runtime.portfolio.next_required_boundary()
        clock.advance(due+timedelta(seconds=12))
        await runtime.poll()
        assert not runtime.portfolio.pending
        assert tuple(point.model_dump_json() for point in runtime.portfolio.curve)[:len(prior)] == prior
        if open_position:
            assert runtime.portfolio.positions()[0].position.status == 'INCOMPLETE'
            assert runtime.portfolio.state(clock.now()).marked_equity is None
        else:
            assert runtime.portfolio.expired_count == 1 and not runtime.portfolio.active


@pytest.mark.asyncio
async def test_shutdown_does_not_invent_a_close_for_open_exposure():
    async with running() as (runtime, hub, clock):
        for event in wave_bars():
            await publish_group(runtime, hub, clock, [event])
            if runtime.portfolio.active:
                break
        assert runtime.portfolio.active
        before = tuple(runtime.portfolio.curve)
    assert tuple(runtime.portfolio.curve) == before
    assert runtime.portfolio.positions()[0].position.status == 'INCOMPLETE'
    assert not runtime.portfolio.closes
