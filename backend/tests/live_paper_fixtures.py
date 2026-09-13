"""Injected wall/monotonic clocks; no real timeout waits or network."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from backtest_fixtures import START, bar
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.market_data_hub import MarketDataHub
from src.domain.market_data import ConnectionStatus, EventType, MarketConnectionState


class ManualLiveClock:
    def __init__(self):
        self.timestamp = START
        self.tick = 0.0
        self.waiters = []

    def now(self):
        return self.timestamp

    def monotonic(self):
        return self.tick

    def advance(self, timestamp=None, seconds=0):
        target = timestamp if timestamp is not None else self.timestamp+timedelta(seconds=seconds)
        self.tick += max(0, (target-self.timestamp).total_seconds())
        self.timestamp = target
        for deadline, future in tuple(self.waiters):
            if deadline <= self.tick and not future.done():
                future.set_result(None)

    async def sleep(self, seconds):
        future = asyncio.get_running_loop().create_future()
        pair = (self.tick+seconds, future)
        self.waiters.append(pair)
        try:
            await future
        finally:
            self.waiters.remove(pair)


async def checkpoint(predicate, attempts=300):
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    assert predicate(), 'deterministic event-loop checkpoints exhausted'


def connect(hub, clock, generation=1, status=ConnectionStatus.CONNECTED):
    hub.update_connection(MarketConnectionState(connection_id='injected_public', event_types=(EventType.KLINE,),
        status=status, changed_at=clock.now(), generation=generation))


@asynccontextmanager
async def running(symbols=('BTCUSDT',), interval='1m', settings=None, **options):
    clock = ManualLiveClock()
    hub = MarketDataHub(symbols, kline_intervals=(interval,), clock=clock.now)
    connect(hub, clock)
    config = LivePaperSettings.model_validate((settings or LivePaperSettings()).model_copy(update={'enabled': True}))
    coordinator = LivePaperCoordinator(hub, settings=config, clock=clock, **options)
    task = asyncio.create_task(coordinator.run(), name='live-paper-coordinator')
    await checkpoint(lambda: coordinator.running or task.done())
    try:
        yield coordinator, hub, clock
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert hub.status().subscriber_count == 0
        assert not clock.waiters
        if coordinator.analysis.hub is not None:
            assert coordinator.analysis.hub.status().subscriber_count == 0
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith('live-paper-')]


async def publish_group(coordinator, hub, clock, events):
    clock.advance(max(event.received_at for event in events))
    target = coordinator.counts['finalized_batches']+1
    for event in events:
        hub.publish(event, connection_id='injected_public')
    await checkpoint(lambda: coordinator.counts['finalized_batches'] == target or not coordinator.running)
    assert coordinator.running, [event.reason for event in coordinator.events]


def second_bar(index=0, symbol='BTCUSDT', **changes):
    opened = START+timedelta(seconds=index)
    end = opened+timedelta(seconds=1)
    return bar(index, symbol=symbol, interval='1s', open_time=opened, close_time=end,
               event_time=end, received_at=end, **changes)
