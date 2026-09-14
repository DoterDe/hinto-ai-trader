"""Small canonical checkpoints; every store test supplies its own temporary path."""

from decimal import Decimal
from contextlib import asynccontextmanager

from backtest_fixtures import START, bar
from src.application.paper_portfolio_ledger import zero_pnl
from src.domain.paper_persistence import (
    AnalysisCheckpoint, AnalyticalObservation, BatcherCheckpoint, CandleHistoryCheckpoint,
    CheckpointBounds, LedgerCheckpoint, PaperCheckpoint, PaperCompatibility, SealedBoundary,
)
from src.strategies.identity import identity


@asynccontextmanager
async def durable_runtime(path, *, symbols=('BTCUSDT',), interval='1m', start_at=None, **options):
    from live_paper_fixtures import ManualLiveClock, connect
    from src.application.live_paper_coordinator import LivePaperCoordinator
    from src.application.live_paper_settings import LivePaperSettings
    from src.application.market_data_hub import MarketDataHub
    from src.application.paper_persistence_settings import PaperPersistenceSettings
    clock = ManualLiveClock()
    if start_at is not None:
        clock.advance(start_at)
    hub = MarketDataHub(symbols, kline_intervals=(interval,), clock=clock.now)
    connect(hub, clock)
    runtime = LivePaperCoordinator(hub, clock=clock,
        settings=options.pop('settings', LivePaperSettings(enabled=True, event_history_limit=15,
            curve_history_limit=20, position_history_limit=10)),
        persistence_settings=PaperPersistenceSettings(enabled=True, path=path, checkpoint_history=3, event_history=5), **options)
    try:
        assert await runtime.persistence.start(runtime), runtime.persistence.state
        runtime.running = True
        yield runtime, hub, clock
    finally:
        runtime.running = False
        await runtime.analysis.stop()
        await runtime.persistence.close()
        assert hub.status().subscriber_count == 0
        if runtime.analysis.hub is not None:
            assert runtime.analysis.hub.status().subscriber_count == 0


async def admit(runtime, hub, clock, events):
    from src.application.market_data_hub import ClosedBarObservation
    clock.advance(max(clock.now(), max(event.received_at for event in events)))
    for event in events:
        hub.publish(event, connection_id='injected_public')
        await runtime.accept(ClosedBarObservation(bar=event, connection_id='injected_public', generation=1))


def sample_checkpoint(index=0, **changes):
    candle = bar(index)
    boundary = candle.close_time
    return PaperCheckpoint(session_id='session_test', session_created_at=START,
        checkpoint_at=boundary, durable_boundary=boundary,
        compatibility=PaperCompatibility(runtime_version='live-paper-v1', feature_version='features-v1',
            strategy_version='strategy-engine-v1', decision_version='decision-engine-v1',
            portfolio_version='paper-portfolio-engine-v1', backtest_version='backtest-engine-v1',
            symbols=('BTCUSDT',), interval='1m', runtime_settings_id='runtime_test',
            feature_settings_id='features_test', strategy_settings_id='strategies_test',
            decision_policy_id='decision_test', portfolio_policy_id='portfolio_test', cost_settings_id='costs_test'),
        bounds=CheckpointBounds(events=7, closes=3, curve=9, sealed=2, candles=50, holding_bars=5),
        ledger=LedgerCheckpoint(closed_pnl=zero_pnl(), peak=Decimal('100000.0000'), last_boundary=boundary),
        batcher=BatcherCheckpoint(watermark=boundary, sealed=(SealedBoundary(boundary=boundary,
            fingerprints=(('BTCUSDT', identity('live_bar', candle)),)),)),
        analysis=AnalysisCheckpoint(clock=boundary, generation=1,
            histories=(CandleHistoryCheckpoint(symbol='BTCUSDT', bars=(candle,), resets=1,
                last_reset='connection_changed'),), observations=(AnalyticalObservation(bar=candle, generation=1),)),
        generation=1, **changes)
