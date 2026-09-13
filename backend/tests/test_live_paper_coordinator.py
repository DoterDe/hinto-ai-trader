import asyncio
from datetime import timedelta

import pytest

from backtest_fixtures import START, bar, wave_bars
from live_paper_fixtures import ManualLiveClock, checkpoint, connect, publish_group, running, second_bar
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.market_data_hub import ClosedBarObservation, MarketDataHub
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.market_data import ConnectionStatus


@pytest.mark.asyncio
async def test_disabled_runtime_has_no_subscriber_or_analytical_task():
    clock = ManualLiveClock()
    hub = MarketDataHub(('BTCUSDT',), clock=clock.now)
    runtime = LivePaperCoordinator(hub, clock=clock, settings=LivePaperSettings(enabled=False))
    await runtime.run()
    assert runtime.health() == ('DISABLED', ())
    assert hub.status().subscriber_count == 0 and runtime.analysis.task is None


@pytest.mark.asyncio
async def test_start_once_open_candles_do_not_trigger_and_shutdown_cleans_up():
    async with running() as (runtime, hub, clock):
        with pytest.raises(RuntimeError, match='only once'):
            await runtime.run()
        clock.advance(bar().received_at)
        hub.publish(bar(is_closed=False), connection_id='injected_public')
        for _ in range(8):
            await asyncio.sleep(0)
        assert not runtime.decisions and not runtime.portfolio.curve and runtime.analysis.task is None
    assert runtime.health()[0] == 'STOPPED'


@pytest.mark.asyncio
async def test_warmup_running_then_stale_without_new_decisions():
    async with running() as (runtime, hub, clock):
        data = list(wave_bars())
        await publish_group(runtime, hub, clock, [data[0]])
        assert runtime.health()[0] == 'WARMING_UP'
        for event in data[1:]:
            await publish_group(runtime, hub, clock, [event])
        assert runtime.health() == ('RUNNING', ())
        assert len(runtime.decisions) == 80 and runtime.portfolio.completed_count > 0
        count = len(runtime.decisions)
        clock.advance(seconds=10)
        await runtime.poll()
        assert runtime.health()[0] == 'DEGRADED' and 'market_feed_stale' in runtime.health()[1]
        assert len(runtime.decisions) == count


@pytest.mark.asyncio
async def test_repeated_and_permuted_full_analytical_artifacts_identical():
    symbols = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
    expected = None
    for order in (symbols, symbols, tuple(reversed(symbols)), symbols[1:]+symbols[:1]):
        async with running(symbols, portfolio_settings=PaperPortfolioSettings(max_open_positions=1)) as (runtime, hub, clock):
            for events in zip(*(wave_bars(symbol=symbol) for symbol in order)):
                await publish_group(runtime, hub, clock, events)
            artifacts = ([item.model_dump_json() for item in runtime.decisions],
                [item.model_dump_json() for item in runtime.portfolio.curve],
                [item.model_dump_json() for item in runtime.portfolio.closes])
            expected = artifacts if expected is None else expected
            assert artifacts == expected
            assert {item.position.reservation.symbol for item in runtime.portfolio.closes} == {'BTCUSDT'}


@pytest.mark.asyncio
async def test_delayed_close_cannot_read_newer_closed_bar_from_live_hub():
    async with running(('BTCUSDT', 'ETHUSDT'), interval='1s') as (runtime, hub, clock):
        first, newer = second_bar(), second_bar(1, closed='900')
        clock.advance(newer.received_at)
        # The ordinary hub cache already contains t+1 when the ETH t bar arrives.
        for event in (first, newer, second_bar(symbol='ETHUSDT')):
            hub.publish(event, connection_id='injected_public')
        await checkpoint(lambda: len(runtime.decisions) == 2 or not runtime.running)
        assert runtime.running
        assert hub.latest('BTCUSDT').events['kline:1s'].close == 900
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 1
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candle_time == first.close_time
        assert runtime.analysis.hub.latest('BTCUSDT').events['kline:1s'].close == first.close


@pytest.mark.asyncio
async def test_future_price_change_preserves_entire_prior_prefix():
    expected = None
    for change in (False, True):
        async with running() as (runtime, hub, clock):
            for index, event in enumerate(wave_bars()):
                if change and index == 70:
                    event = bar(index, opened='900', closed='910')
                await publish_group(runtime, hub, clock, [event])
            cutoff = bar(70).close_time
            prefix = ([item.model_dump_json() for item in runtime.decisions if item.boundary < cutoff],
                      [item.model_dump_json() for item in runtime.portfolio.curve if item.state.timestamp < cutoff])
            expected = prefix if expected is None else expected
            assert prefix == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('age,admitted', [(9.999, True), (10, False), (61, False)])
async def test_real_age_is_checked_before_canonical_time_evaluation(age, admitted):
    async with running() as (runtime, hub, clock):
        event = bar()
        clock.advance(event.received_at+timedelta(seconds=age))
        hub.publish(event, connection_id='injected_public')
        await checkpoint(lambda: runtime.counts['finalized_batches'] == 1 or not runtime.running)
        assert runtime.running
        assert len(runtime.decisions) == int(admitted)
        assert runtime.counts['admitted_bars'] == int(admitted)
        if not admitted:
            assert runtime.counts['stale_finalized_bar'] == 1


@pytest.mark.asyncio
async def test_original_publication_and_receipt_times_retained():
    async with running() as (runtime, hub, clock):
        event = bar(event_time=bar().close_time+timedelta(milliseconds=100),
                    received_at=bar().close_time+timedelta(milliseconds=200))
        await publish_group(runtime, hub, clock, [event])
        record = runtime.decisions[0]
        assert record.published_at == event.event_time and record.received_at == event.received_at
        assert record.portfolio.upstream.generated_at == event.close_time
        assert record.features.microstructure.values is None


@pytest.mark.asyncio
async def test_stale_connection_generation_rejected_before_admission():
    async with running() as (runtime, hub, clock):
        event = bar()
        clock.advance(event.received_at)
        connect(hub, clock, generation=2)
        await runtime.accept(ClosedBarObservation(bar=event, connection_id='injected_public', generation=1))
        assert runtime.counts['obsolete_generation'] == 1 and not runtime.decisions


@pytest.mark.asyncio
async def test_reconnect_rewarms_existing_features_without_formulas_change():
    async with running() as (runtime, hub, clock):
        for event in wave_bars(55):
            await publish_group(runtime, hub, clock, [event])
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 55
        connect(hub, clock, generation=2)
        await publish_group(runtime, hub, clock, [bar(55)])
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 1
        assert runtime.health()[0] == 'WARMING_UP'


@pytest.mark.asyncio
async def test_timeout_missing_and_late_history_immutable_with_injected_timer():
    async with running(('BTCUSDT', 'ETHUSDT')) as (runtime, hub, clock):
        clock.advance(bar().received_at)
        hub.publish(bar(), connection_id='injected_public')
        await checkpoint(lambda: runtime.batcher.pending_count == 1)
        clock.advance(seconds=1.5)
        await runtime.poll()
        assert runtime.counts['finalized_batches'] == 1 and len(runtime.decisions) == 1
        before = runtime.portfolio.curve[-1].model_dump_json()
        hub.publish(bar(symbol='ETHUSDT'), connection_id='injected_public')
        await checkpoint(lambda: runtime.counts['late_bar'] == 1)
        assert runtime.portfolio.curve[-1].model_dump_json() == before
        assert runtime.health()[0] == 'DEGRADED'


@pytest.mark.asyncio
async def test_duplicate_and_conflict_observable_even_when_hub_cache_rejects_them():
    async with running() as (runtime, hub, clock):
        await publish_group(runtime, hub, clock, [bar()])
        before = runtime.portfolio.curve[-1].model_dump_json()
        hub.publish(bar(), connection_id='injected_public')
        await checkpoint(lambda: runtime.counts['duplicate_bar'] == 1)
        hub.publish(bar(closed='110'), connection_id='injected_public')
        await checkpoint(lambda: runtime.counts['conflicting_late_bar'] == 1)
        assert len(runtime.decisions) == 1 and runtime.portfolio.curve[-1].model_dump_json() == before
        assert hub.status().ignored_events == 2


@pytest.mark.asyncio
async def test_queue_overflow_cannot_admit_a_held_observation_before_loss_handling():
    async with running(settings=LivePaperSettings(queue_limit=2)) as (runtime, hub, clock):
        await checkpoint(lambda: bool(clock.waiters))
        clock.advance(bar(5).received_at)
        for index in range(6):
            hub.publish(bar(index), connection_id='injected_public')
        await checkpoint(lambda: runtime.counts['subscriber_gap'] == 1)
        assert not runtime.decisions and not runtime.portfolio.pending
        await publish_group(runtime, hub, clock, [bar(6)])
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 1


@pytest.mark.asyncio
async def test_exception_is_sanitized_and_consumers_are_removed(monkeypatch):
    async with running() as (runtime, hub, clock):
        def broken(*args, **kwargs):
            raise RuntimeError('INTERNAL_STACK_MARKER')
        monkeypatch.setattr(runtime.analysis, 'evaluate', broken)
        clock.advance(bar().received_at)
        hub.publish(bar(), connection_id='injected_public')
        await checkpoint(lambda: not runtime.running)
        assert runtime.health()[0] == 'ERROR'
        assert 'INTERNAL_STACK_MARKER' not in ''.join(item.model_dump_json() for item in runtime.events)


@pytest.mark.asyncio
async def test_long_stream_all_runtime_histories_remain_bounded():
    limits = LivePaperSettings(event_history_limit=11, curve_history_limit=13, position_history_limit=2)
    async with running(settings=limits) as (runtime, hub, clock):
        for event in wave_bars(650):
            await publish_group(runtime, hub, clock, [event])
            assert len(runtime.events) <= 11 and len(runtime.decisions) <= 11
            assert len(runtime.portfolio.curve) <= 13 and len(runtime.portfolio.closes) <= 2
        assert runtime.latest_analyses['BTCUSDT'].features.closed_candles == 500
        assert runtime.counts['admitted_bars'] == 650


def test_closed_subscription_preserves_normal_subscriber_semantics_and_bounds():
    clock = ManualLiveClock()
    hub = MarketDataHub(('BTCUSDT',), clock=clock.now)
    connect(hub, clock)
    clock.advance(bar().received_at)
    with hub.subscribe(4) as ordinary, hub.subscribe_closed_bars(2) as closed:
        for event in (bar(), bar(), bar(closed='110')):
            hub.publish(event, connection_id='injected_public')
        assert ordinary.qsize() == 1 and closed.qsize() == 2
        assert closed.dropped_events == 1 and ordinary.dropped_events == 0
        observation = closed.get_nowait()
        assert observation.generation == 1 and observation.connection_id == 'injected_public'
        assert hub.status().subscriber_count == 2
    assert hub.status().subscriber_count == 0
