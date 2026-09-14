"""Narrow checkpoint adapter for the existing live runtime's owned state.

Private history/admission fields are deliberately confined to this adapter.
Analytical formulas and public price caches are never replaced or evaluated here.
"""

from typing import TYPE_CHECKING
from collections import OrderedDict

from src.application.backtest_identity import BACKTEST_ENGINE_VERSION
from src.application.decision_identity import DECISION_ENGINE_VERSION, policy_identity
from src.application.paper_portfolio_identity import PORTFOLIO_ENGINE_VERSION
from src.application.strategy_engine import ENGINE_VERSION
from src.application.feature_history import FeatureHistory
from src.application.historical_bars import validate_bar
from src.application.paper_position_evidence import PositionEvidenceIdentity
from src.application.paper_portfolio_math import marked_pnl
from src.domain.market_data import ConnectionStatus, EventType, MarketConnectionState
from src.domain.paper_persistence import (
    AnalysisCheckpoint, AnalyticalObservation, BatcherCheckpoint, CandleHistoryCheckpoint,
    CheckpointBounds, LedgerCheckpoint, PaperCheckpoint, PaperCompatibility, PositionEvidence, SealedBoundary,
)
from src.strategies.identity import identity

if TYPE_CHECKING:
    from src.application.live_paper_coordinator import LivePaperCoordinator


def compatibility(runtime: 'LivePaperCoordinator') -> PaperCompatibility:
    return PaperCompatibility(runtime_version='live-paper-v1', feature_version='feature-engine-v1',
        strategy_version=ENGINE_VERSION, decision_version=DECISION_ENGINE_VERSION,
        portfolio_version=PORTFOLIO_ENGINE_VERSION, backtest_version=BACKTEST_ENGINE_VERSION,
        symbols=runtime.batcher.symbols, interval=runtime.batcher.interval,
        runtime_settings_id=identity('live_settings', (runtime.settings, runtime.hub.stale_after_seconds)),
        feature_settings_id=identity('feature_settings', runtime.feature_settings),
        strategy_settings_id=identity('settings', runtime.strategy_settings),
        decision_policy_id=policy_identity(runtime.decision_settings, runtime.batcher.symbols),
        portfolio_policy_id=runtime.portfolio.policy.policy_id, cost_settings_id=runtime.portfolio.cost_id)


def capture(runtime: 'LivePaperCoordinator', session_id: str, created_at) -> PaperCheckpoint:
    book, batcher, view, limits = runtime.portfolio, runtime.batcher, runtime.analysis, runtime.settings
    if book.last_boundary is None or book._failed:
        raise ValueError('only successful finalized portfolio states can be checkpointed')
    analysis = None
    if view.features is not None:
        # Settle the isolated queue even for an empty admitted group. This only
        # records closed history already admitted at the explicit replay clock.
        view.features._refresh()
        observations = []
        for symbol in batcher.symbols:
            snapshot = view.hub.latest(symbol)
            key = f'kline:{batcher.interval}'
            if key in snapshot.events:
                observations.append(AnalyticalObservation(bar=snapshot.events[key], generation=snapshot.streams[key].generation))
        connection = view.features._connection
        analysis = AnalysisCheckpoint(clock=view.clock(), generation=connection[1] if connection else 0,
            histories=tuple(CandleHistoryCheckpoint(symbol=symbol, bars=history.closed,
                resets=history.resets, last_reset=history.last_reset) for symbol, history in sorted(view.features._histories.items())),
            observations=tuple(observations))
    return PaperCheckpoint(session_id=session_id, session_created_at=created_at, checkpoint_at=runtime.clock.now(),
        durable_boundary=book.last_boundary, compatibility=compatibility(runtime),
        bounds=CheckpointBounds(events=limits.event_history_limit, closes=limits.position_history_limit,
            curve=limits.curve_history_limit, sealed=limits.pending_batch_limit,
            candles=runtime.feature_settings.history_limit, holding_bars=book.costs.holding_period_bars),
        ledger=LedgerCheckpoint(reservations=tuple(v for _, v in sorted(book.pending.items())),
            positions=tuple(v for _, v in sorted(book.active.items())), marks=tuple(sorted(book.marks.items())),
            evidence=tuple(PositionEvidence(symbol=s, fingerprints=tuple(v.fingerprints)) for s, v in sorted(book.evidence.items())),
            closes=tuple(book.closes), curve=tuple(book.curve), closed_pnl=book.closed_pnl, peak=book.peak,
            last_boundary=book.last_boundary, seen=tuple(book._seen.items()), expired_count=book.expired_count,
            opened_count=book.opened_count, completed_count=book.completed_count, duplicate_count=book.duplicate_count),
        # _flush may have sealed several returned groups before the first is
        # applied. Never checkpoint a later, unapplied group's watermark.
        batcher=BatcherCheckpoint(watermark=max(book.last_boundary, runtime._admission_floor or book.last_boundary), sealed=tuple(SealedBoundary(boundary=stamp,
            fingerprints=tuple(sorted(values.items()))) for stamp, values in batcher._sealed.items() if stamp <= book.last_boundary)),
        analysis=analysis, generation=runtime._generation, decisions=tuple(runtime.decisions),
        latest_analyses=tuple(v for _, v in sorted(runtime.latest_analyses.items())), events=tuple(runtime.events),
        counters=tuple(sorted(runtime.counts.items())), last_problem=runtime._last_problem)


async def restore(runtime: 'LivePaperCoordinator', checkpoint: PaperCheckpoint) -> None:
    """Restore committed evidence, never replay a decision or publish to live Hub."""
    checkpoint = PaperCheckpoint.model_validate(checkpoint)
    if compatibility(runtime) != checkpoint.compatibility:
        raise ValueError('incompatible recovery configuration')
    ledger, book, batcher = checkpoint.ledger, runtime.portfolio, runtime.batcher
    if ledger.opened_count != ledger.completed_count + len(ledger.positions) or ledger.completed_count < len(ledger.closes):
        raise ValueError('inconsistent lifetime position counters')
    for reservation in ledger.reservations + tuple(p.reservation for p in ledger.positions):
        if reservation.policy_id != book.policy.policy_id:
            raise ValueError('reservation policy mismatch')
    marks = dict(ledger.marks)
    for position in ledger.positions:
        if position.backtest_settings_id != book.cost_id or position.interval != book.interval:
            raise ValueError('position cost or interval mismatch')
        if position.status == 'OPEN':
            calculated = marked_pnl(position.reservation.virtual_notional, position.entry_price_raw,
                position.last_mark_price, position.reservation.direction, book.costs).net_pnl
            if marks[position.reservation.symbol] != calculated:
                raise ValueError('position mark does not reconcile')
    view = runtime.analysis
    if checkpoint.analysis is not None:
        state = checkpoint.analysis
        histories = {}
        for saved in state.histories:
            history = FeatureHistory(saved.symbol, batcher.interval, runtime.feature_settings.history_limit)
            for bar in saved.bars:
                validate_bar(bar)
                if not history.accept(bar, now=state.clock):
                    raise ValueError('invalid recovered closed history')
            history.resets, history.last_reset = saved.resets, saved.last_reset
            histories[saved.symbol] = history
        await view.start(state.clock)
        def connection(generation):
            view.hub.update_connection(MarketConnectionState(connection_id='live_closed_bars', event_types=(EventType.KLINE,),
                status=ConnectionStatus.CONNECTED, changed_at=state.clock, generation=generation))
        for observation in sorted(state.observations, key=lambda item: (item.generation, item.bar.symbol)):
            validate_bar(observation.bar)
            connection(observation.generation)
            view.hub.publish(observation.bar, connection_id='live_closed_bars')
        connection(state.generation)
        view.features._discard_pending()
        view.features._connection = ('live_closed_bars', state.generation, ConnectionStatus.CONNECTED)
        view.features._last_now = state.clock
        view.features._histories = histories
    book.pending = {r.symbol: r for r in ledger.reservations}
    book.active = {p.reservation.symbol: p for p in ledger.positions}
    book.marks = marks
    book.evidence = {e.symbol: PositionEvidenceIdentity(book.costs.holding_period_bars, e.fingerprints) for e in ledger.evidence}
    book.closes.extend(ledger.closes)
    book.curve.extend(ledger.curve)
    book.closed_pnl, book.peak, book.last_boundary = ledger.closed_pnl, ledger.peak, ledger.last_boundary
    book._seen = OrderedDict(ledger.seen)
    for name in ('expired_count', 'opened_count', 'completed_count', 'duplicate_count'):
        setattr(book, name, getattr(ledger, name))
    if book.state(ledger.last_boundary).peak_equity != ledger.peak:
        raise ValueError('persisted peak equity is inconsistent')
    batcher.watermark = checkpoint.batcher.watermark
    runtime._admission_floor = checkpoint.batcher.watermark
    batcher._sealed = OrderedDict((s.boundary, dict(s.fingerprints)) for s in checkpoint.batcher.sealed)
    runtime.decisions.extend(checkpoint.decisions)
    runtime.latest_analyses = {a.features.symbol: a for a in checkpoint.latest_analyses}
    runtime.events.extend(checkpoint.events)
    runtime.counts.update(dict(checkpoint.counters))
    runtime._last_problem = checkpoint.last_problem
    runtime._generation = checkpoint.generation
    runtime._recovered_bootstrap = True
