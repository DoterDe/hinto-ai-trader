"""One bounded public-close consumer; deterministic paper artifacts, no execution."""

import asyncio
from collections import Counter, deque
from datetime import datetime, timedelta

from src.application.backtest_settings import BacktestSettings
from src.application.decision_settings import DecisionSettings
from src.application.feature_settings import FeatureSettings
from src.application.live_bar_batcher import BatchResult, LiveBarBatcher, canonical_bar
from src.application.live_paper_analysis import LivePaperAnalysis
from src.application.live_paper_clock import LiveClock, SystemLiveClock
from src.application.live_paper_portfolio import LivePaperPortfolio
from src.application.live_paper_settings import LivePaperSettings
from src.application.market_data_hub import ClosedBarObservation, MarketDataHub
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.application.strategy_settings import StrategySettings
from src.domain.live_paper import LiveAnalysis, LiveBarBatch, LivePaperEvent, LivePaperStatus as Status
from src.domain.market_data import ConnectionStatus
from src.strategies.identity import identity


class LivePaperCoordinator:
    def __init__(self, hub: MarketDataHub, *, settings: LivePaperSettings | None = None,
                 portfolio_settings: PaperPortfolioSettings | None = None, costs: BacktestSettings | None = None,
                 feature_settings: FeatureSettings | None = None, strategy_settings: StrategySettings | None = None,
                 decision_settings: DecisionSettings | None = None, clock: LiveClock | None = None) -> None:
        self.hub = hub
        self.settings = LivePaperSettings.model_validate(settings) if settings is not None else LivePaperSettings()
        self.clock = clock or SystemLiveClock()
        self.portfolio_settings = portfolio_settings if portfolio_settings is not None else PaperPortfolioSettings()
        self.costs = costs if costs is not None else BacktestSettings()
        self.feature_settings = FeatureSettings.model_validate(feature_settings.model_dump()) if feature_settings is not None else FeatureSettings()
        self.strategy_settings = StrategySettings.model_validate(strategy_settings) if strategy_settings is not None else StrategySettings()
        self.decision_settings = DecisionSettings.model_validate(decision_settings) if decision_settings is not None else DecisionSettings()
        self.batcher = LiveBarBatcher(hub.symbols, interval=hub.kline_intervals[0], settings=self.settings, monotonic=self.clock.monotonic)
        self.portfolio = LivePaperPortfolio(hub.symbols, interval=self.batcher.interval, runtime=self.settings,
            settings=self.portfolio_settings, costs=self.costs)
        self.analysis = LivePaperAnalysis(self.batcher.symbols, self.batcher.interval, self.feature_settings,
            self.strategy_settings, self.decision_settings, hub.stale_after_seconds)
        self.events: deque[LivePaperEvent] = deque(maxlen=self.settings.event_history_limit)
        self.decisions: deque[LiveAnalysis] = deque(maxlen=self.settings.event_history_limit)
        self.latest_analyses: dict[str, LiveAnalysis] = {}
        self.counts: Counter[str] = Counter()
        self.running = False
        self.started_at: datetime | None = None
        self._started = False
        self._status = Status.STARTING if self.settings.enabled else Status.DISABLED
        self._connection = None
        self._generation = 0
        self._drops = 0
        self._last_problem: str | None = None
        self._last_wall = None

    def health(self) -> tuple[Status, tuple[str, ...]]:
        if self._status in (Status.DISABLED, Status.STARTING, Status.STOPPING, Status.STOPPED, Status.ERROR):
            return self._status, (self._last_problem,) if self._last_problem else ()
        reasons = []
        if self.analysis.task is not None and self.analysis.task.done():
            reasons.append('analytical_unavailable')
        if any(self.hub.latest(symbol).streams[f'kline:{self.batcher.interval}'].stale for symbol in self.batcher.symbols):
            reasons.append('market_feed_stale')
        if self.portfolio.state(self.clock.now()).marked_equity is None:
            reasons.append('portfolio_valuation_unknown')
        if self._last_problem:
            reasons.append(self._last_problem)
        if reasons:
            return Status.DEGRADED, tuple(dict.fromkeys(reasons))
        if any(symbol not in self.latest_analyses or self.latest_analyses[symbol].strategy.readiness != 'ready'
               for symbol in self.batcher.symbols):
            return Status.WARMING_UP, ('feature_pipeline_warming_up',)
        return Status.RUNNING, ()

    def _event(self, reason: str, explanation: str, *, symbol=None, related_id=None,
               category='runtime', severity='warning', timestamp=None) -> None:
        self.counts[reason] += 1
        timestamp = timestamp or self.clock.now()
        self.events.append(LivePaperEvent(event_id=identity('live_event',
            (reason, timestamp, symbol, related_id, self.counts[reason])), timestamp=timestamp,
            category=category, severity=severity, symbol=symbol, reason=reason,
            explanation=explanation, related_id=related_id))

    def _synchronize(self) -> None:
        now = self.clock.now()
        if self._last_wall is not None and now < self._last_wall:
            raise ValueError('live wall clock moved backwards')
        self._last_wall = now
        stream = self.hub.latest(self.batcher.symbols[0]).streams[f'kline:{self.batcher.interval}']
        connection = next((item for item in self.hub.status().connections if item.connection_id == stream.connection_id), None)
        token = None if connection is None else (connection.connection_id, connection.generation, connection.status)
        if token != self._connection:
            if self._connection is not None:
                self.batcher.discard_pending()
                self.portfolio.invalidate()
                self._event('connection_changed', 'Public candle connection changed; continuity must warm up again.', category='feed')
                self._last_problem = 'connection_changed'
            self._connection = token
            self._generation += 1

    async def accept(self, observation: ClosedBarObservation) -> None:
        """Explicit boundary also used by deterministic offline integration tests."""
        if not self.running:
            raise RuntimeError('live coordinator is not running')
        self._synchronize()
        observation = ClosedBarObservation.model_validate(observation)
        token = (observation.connection_id, observation.generation, ConnectionStatus.CONNECTED)
        if self._connection != token:
            self._event('obsolete_generation', 'A candle belongs to an obsolete public connection.', category='feed')
            return
        result = self.batcher.push(observation.bar, now=self.clock.now())
        await self._result(result)

    async def _result(self, result: BatchResult) -> None:
        # Already finalized earlier groups must be applied before diagnostics
        # caused by the newly arriving (possibly later) observation.
        for batch in result.batches:
            await self._apply(batch)
        for notice in result.notices:
            if notice.reason == 'unfinished_candle':
                continue
            self._event(notice.reason, 'Public candle was not admitted: '+notice.reason.replace('_', ' ')+'.',
                        symbol=notice.symbol, category='batch')
            if notice.reason != 'duplicate_bar':
                self._last_problem = notice.reason
            if notice.reason in ('conflicting_bar', 'conflicting_late_bar', 'batch_buffer_full'):
                self.portfolio.invalidate()
                self._generation += 1

    async def _apply(self, batch: LiveBarBatch) -> None:
        if batch.conflicting_symbols:
            self.portfolio.invalidate()
            self._generation += 1
        token = self._connection
        await self.analysis.start(batch.boundary)
        # Lazy consumer startup yields once. Recheck provenance and real age
        # afterwards, before admitting any data to the canonical analytical view.
        self._synchronize()
        now = self.clock.now()
        maximum = min(self.hub.stale_after_seconds, float(self.strategy_settings.max_feature_age_seconds),
                      float(self.decision_settings.max_strategy_snapshot_age_seconds))
        accepted = tuple(event for event in batch.bars if token == self._connection and all(0 <= (now-stamp).total_seconds() < maximum
            for stamp in (batch.boundary, event.event_time, event.received_at)))
        if token != self._connection:
            self._event('generation_changed_during_batch', 'Connection changed while the close group was being prepared.', category='feed')
        if len(accepted) != len(batch.bars):
            self._event('stale_finalized_bar', 'Delayed candles failed the existing freshness limits.', category='feed')
        missing = tuple(symbol for symbol in self.batcher.symbols if symbol not in {bar.symbol for bar in accepted})
        self._last_problem = 'missing_symbol_bar' if missing else None
        if missing:
            self._event('missing_symbol_bar', 'A close group is missing required public candles; no bars were invented.',
                        category='batch', timestamp=batch.boundary)
        canonical = tuple(canonical_bar(event) for event in accepted)
        evaluated = self.analysis.evaluate(batch.boundary, canonical, self._generation)
        records = self.portfolio.advance(batch.boundary, canonical, tuple(item[2] for item in evaluated))
        by_symbol = {item[0].symbol: item for item in evaluated}
        raw = {event.symbol: event for event in accepted}
        for record in records:
            symbol = record.upstream.symbol
            features, strategy, _ = by_symbol[symbol]
            item = LiveAnalysis(boundary=batch.boundary, published_at=raw[symbol].event_time,
                received_at=raw[symbol].received_at, connection_id=token[0], connection_generation=token[1],
                features=features, strategy=strategy, portfolio=record)
            self.decisions.append(item)
            self.latest_analyses[symbol] = item
            self._event(record.reason.value, 'Virtual portfolio: '+record.reason.value.replace('_', ' ')+'.',
                symbol=symbol, related_id=record.portfolio_decision_id, category='portfolio', severity='info', timestamp=batch.boundary)
        self.counts['finalized_batches'] += 1
        self.counts['admitted_bars'] += len(accepted)

    async def poll(self) -> None:
        self._synchronize()
        await self._result(self.batcher.poll())
        due = self.portfolio.next_required_boundary()
        grace = timedelta(seconds=self.hub.stale_after_seconds+self.settings.batch_timeout_ms/1000)
        if due is not None and self.clock.now() >= due+grace:
            # No bars at all can arrive for this required boundary. Explicit empty
            # evidence expires reservations / invalidates marks, never a price.
            if self.portfolio.last_boundary is None or due > self.portfolio.last_boundary:
                self.portfolio.advance(due, ())
                self.batcher.discard_pending()
                self.batcher.watermark = max(self.batcher.watermark, due) if self.batcher.watermark else due
                self._last_problem = 'missing_symbol_bar'
                self._event('missing_symbol_bar', 'A required holding or entry candle never arrived.', category='batch')

    async def run(self) -> None:
        if self._started:
            raise RuntimeError('live coordinator can start only once')
        self._started = True
        if not self.settings.enabled:
            self._status = Status.DISABLED
            return
        self.running = True
        self.started_at = self.clock.now()
        self._status = Status.WARMING_UP
        self._event('runtime_started', 'Public-data virtual paper runtime started.', severity='info')
        try:
            with self.hub.subscribe_closed_bars(self.settings.queue_limit) as queue:
                processed = 0
                while True:
                    if queue.dropped_events != self._drops:
                        self._drops = queue.dropped_events
                        self.batcher.discard_pending()
                        self.portfolio.invalidate()
                        self._generation += 1
                        self._last_problem = 'subscriber_gap'
                        self._event('subscriber_gap', 'The bounded candle queue lost observations; continuity is unknown.', category='feed')
                        while not queue.empty():
                            queue.get_nowait()
                            queue.task_done()
                    if not queue.empty():
                        observation = queue.get_nowait()
                        try:
                            await self.accept(observation)
                        finally:
                            queue.task_done()
                        processed += 1
                        if processed % 32 == 0:
                            await asyncio.sleep(0)
                        continue
                    consumer = asyncio.create_task(queue.get(), name='live-paper-receive')
                    timer = asyncio.create_task(self.clock.sleep(min(.25, self.settings.batch_timeout_ms/1000)), name='live-paper-timer')
                    try:
                        await asyncio.wait((consumer, timer), return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        if not consumer.done():
                            consumer.cancel()
                        if not timer.done():
                            timer.cancel()
                        await asyncio.gather(consumer, timer, return_exceptions=True)
                    # Settle both tasks before processing: a simultaneous queue
                    # result must not disappear into the timer branch. Overflow
                    # may have occurred while wait() was suspended.
                    if not timer.cancelled():
                        timer.result()
                    if not consumer.cancelled():
                        try:
                            if queue.dropped_events == self._drops:
                                await self.accept(consumer.result())
                        finally:
                            queue.task_done()
                    if queue.dropped_events == self._drops:
                        await self.poll()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._status = Status.ERROR
            self._last_problem = 'runtime_error'
            self.portfolio.invalidate()
            self._event('runtime_error', 'The virtual runtime stopped after an internal error.', severity='error')
        finally:
            failed = self._status == Status.ERROR
            if not failed:
                self._status = Status.STOPPING
            self.batcher.discard_pending()
            self.portfolio.invalidate()
            await self.analysis.stop()
            self.running = False
            if not failed:
                self._status = Status.STOPPED
            self._event('runtime_stopped', 'Virtual runtime stopped; active exposure is unresolved, not liquidated.', severity='info')
