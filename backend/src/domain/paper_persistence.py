"""Versioned recovery values. No database, network, or executable artifacts."""

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from src.domain.backtesting import Count, HistoricalInterval, PositiveCount
from src.domain.live_paper import LiveAnalysis, LiveClose, LivePaperEvent
from src.domain.market_data import KlineEvent, MarketSymbol, NonnegativeDecimal, SafeReason
from src.domain.models import Identifier
from src.domain.paper_portfolio import (
    PaperEntryReservation, PaperPnl, PaperPortfolioCurvePoint, PaperPosition,
    PortfolioDecisionRecord, PortfolioModel,
)

SCHEMA_VERSION = 1
CHECKPOINT_VERSION = 1
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
BarFingerprint = Annotated[str, Field(pattern=r'^bar_[0-9a-f]{64}$')]


class PersistenceStatus(str, Enum):
    DISABLED = 'DISABLED'
    NEW_SESSION = 'NEW_SESSION'
    RECOVERING = 'RECOVERING'
    RECOVERED = 'RECOVERED'
    DURABLE = 'DURABLE'
    DEGRADED = 'DEGRADED'
    INCOMPATIBLE = 'INCOMPATIBLE'
    CORRUPT = 'CORRUPT'
    ERROR = 'ERROR'


class PaperCompatibility(PortfolioModel):
    runtime_version: Identifier
    feature_version: Identifier
    strategy_version: Identifier
    decision_version: Identifier
    portfolio_version: Identifier
    backtest_version: Identifier
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1, max_length=1000)
    interval: HistoricalInterval
    runtime_settings_id: Identifier
    feature_settings_id: Identifier
    strategy_settings_id: Identifier
    decision_policy_id: Identifier
    portfolio_policy_id: Identifier
    cost_settings_id: Identifier

    @model_validator(mode='after')
    def canonical_scope(self) -> Self:
        if self.symbols != tuple(sorted(set(self.symbols))):
            raise ValueError('checkpoint symbols must be unique and sorted')
        return self


class CheckpointBounds(PortfolioModel):
    events: Annotated[int, Field(strict=True, ge=1, le=10000)]
    closes: Annotated[int, Field(strict=True, ge=1, le=10000)]
    curve: Annotated[int, Field(strict=True, ge=1, le=20000)]
    sealed: Annotated[int, Field(strict=True, ge=1, le=64)]
    candles: Annotated[int, Field(strict=True, ge=1, le=10000)]
    holding_bars: PositiveCount


class PositionEvidence(PortfolioModel):
    symbol: MarketSymbol
    fingerprints: tuple[BarFingerprint, ...]


class LedgerCheckpoint(PortfolioModel):
    reservations: tuple[PaperEntryReservation, ...] = ()
    positions: tuple[PaperPosition, ...] = ()
    marks: tuple[tuple[MarketSymbol, Decimal], ...] = ()
    evidence: tuple[PositionEvidence, ...] = ()
    closes: tuple[LiveClose, ...] = ()
    curve: tuple[PaperPortfolioCurvePoint, ...] = ()
    closed_pnl: PaperPnl
    peak: NonnegativeDecimal
    last_boundary: AwareDatetime
    seen: tuple[tuple[Identifier, Identifier], ...] = ()
    expired_count: Count = 0
    opened_count: Count = 0
    completed_count: Count = 0
    duplicate_count: Count = 0


class SealedBoundary(PortfolioModel):
    boundary: AwareDatetime
    fingerprints: tuple[tuple[MarketSymbol, Identifier], ...]


class BatcherCheckpoint(PortfolioModel):
    watermark: AwareDatetime
    sealed: tuple[SealedBoundary, ...] = ()


class CandleHistoryCheckpoint(PortfolioModel):
    symbol: MarketSymbol
    bars: tuple[KlineEvent, ...]
    resets: Count
    last_reset: SafeReason | None


class AnalyticalObservation(PortfolioModel):
    bar: KlineEvent
    generation: Count


class AnalysisCheckpoint(PortfolioModel):
    clock: AwareDatetime
    generation: Count
    histories: tuple[CandleHistoryCheckpoint, ...]
    observations: tuple[AnalyticalObservation, ...]


class PaperCheckpoint(PortfolioModel):
    version: Literal[1] = CHECKPOINT_VERSION
    session_id: Identifier
    session_created_at: AwareDatetime
    checkpoint_at: AwareDatetime
    durable_boundary: AwareDatetime
    compatibility: PaperCompatibility
    bounds: CheckpointBounds
    ledger: LedgerCheckpoint
    batcher: BatcherCheckpoint
    analysis: AnalysisCheckpoint | None
    generation: Count
    decisions: tuple[LiveAnalysis, ...] = ()
    latest_analyses: tuple[LiveAnalysis, ...] = ()
    events: tuple[LivePaperEvent, ...] = ()
    counters: tuple[tuple[SafeReason, Count], ...] = ()
    last_problem: SafeReason | None = None

    @model_validator(mode='after')
    def coherent_state(self) -> Self:
        scope, boundary, book, limits = self.compatibility.symbols, self.durable_boundary, self.ledger, self.bounds
        if book.last_boundary != boundary or self.batcher.watermark < boundary:
            raise ValueError('durable boundary must agree with ledger and admission fence')
        if self.session_created_at > self.checkpoint_at or boundary > self.checkpoint_at:
            raise ValueError('checkpoint chronology is invalid')

        def unique(values: tuple, *, scoped: bool = False, ordered: bool = False) -> None:
            if len(set(values)) != len(values) or (ordered and tuple(sorted(values)) != values):
                raise ValueError('checkpoint keys must be unique and canonically ordered')
            if scoped and not set(values) <= set(scope):
                raise ValueError('checkpoint contains an out-of-scope symbol')

        reservations = tuple(item.symbol for item in book.reservations)
        positions = tuple(item.reservation.symbol for item in book.positions)
        for values in (reservations, positions, tuple(s for s, _ in book.marks),
                       tuple(e.symbol for e in book.evidence)):
            unique(values, scoped=True, ordered=True)
        if set(reservations) & set(positions):
            raise ValueError('checkpoint cannot pyramid a symbol')
        open_positions = {p.reservation.symbol: p for p in book.positions if p.status == 'OPEN'}
        if any(p.status == 'CLOSED' for p in book.positions):
            raise ValueError('active checkpoint positions cannot be closed')
        if set(s for s, _ in book.marks) != set(open_positions) or set(e.symbol for e in book.evidence) != set(open_positions):
            raise ValueError('every open position requires its mark and close-identity evidence')
        for evidence in book.evidence:
            position = open_positions[evidence.symbol]
            if len(evidence.fingerprints) != position.bars_held or len(evidence.fingerprints) > limits.holding_bars:
                raise ValueError('position evidence must match its held horizon')
        if any(p.holding_period_bars != limits.holding_bars or p.entry_time > boundary
               or (p.last_mark_time is not None and p.last_mark_time > boundary) for p in book.positions):
            raise ValueError('position horizon or time is inconsistent')
        if any(r.decision_time > boundary for r in book.reservations):
            raise ValueError('future reservation')
        for values, limit in ((book.closes, limits.closes), (book.curve, limits.curve),
                (book.seen, limits.events), (self.decisions, limits.events), (self.events, limits.events),
                (self.batcher.sealed, limits.sealed), (self.latest_analyses, len(scope))):
            if len(values) > limit:
                raise ValueError('checkpoint retention bound exceeded')
        unique(tuple(key for key, _ in book.seen))  # insertion order is authoritative for eviction
        unique(tuple(key for key, _ in self.counters), ordered=True)
        unique(tuple(c.close.close_id for c in book.closes))
        unique(tuple(d.portfolio.portfolio_decision_id for d in self.decisions))
        unique(tuple(a.features.symbol for a in self.latest_analyses), scoped=True, ordered=True)
        unique(tuple(s.boundary for s in self.batcher.sealed), ordered=True)
        for sealed in self.batcher.sealed:
            if sealed.boundary > self.batcher.watermark:
                raise ValueError('sealed boundary exceeds admission fence')
            unique(tuple(s for s, _ in sealed.fingerprints), scoped=True, ordered=True)
        if any(c.close.exit_time > boundary for c in book.closes) or any(c.state.timestamp > boundary for c in book.curve):
            raise ValueError('future accounting evidence')
        if any(d.boundary > boundary for d in self.decisions) or any(a.boundary > boundary for a in self.latest_analyses):
            raise ValueError('future analytical capture')
        if self.analysis is not None:
            state = self.analysis
            if state.clock > boundary or state.generation > self.generation:
                raise ValueError('future analytical clock or generation')
            if tuple(h.symbol for h in state.histories) != scope:
                raise ValueError('analytical history scope mismatch')
            unique(tuple(o.bar.symbol for o in state.observations), scoped=True, ordered=True)
            for history in state.histories:
                if len(history.bars) > limits.candles:
                    raise ValueError('candle history bound exceeded')
                previous = None
                for bar in history.bars:
                    if bar.symbol != history.symbol or (previous is not None and previous != bar.open_time):
                        raise ValueError('candle history must be per-symbol and contiguous')
                    previous = bar.close_time
            for bar in tuple(b for h in state.histories for b in h.bars) + tuple(o.bar for o in state.observations):
                if (not bar.is_closed or bar.interval != self.compatibility.interval or bar.close_time > state.clock
                        or bar.event_time != bar.close_time or bar.received_at != bar.close_time):
                    raise ValueError('only canonical committed closed candles may be recovered')
            if any(o.generation > state.generation for o in state.observations):
                raise ValueError('future cached generation')
        return self


class CheckpointEnvelope(PortfolioModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    checkpoint_id: Identifier
    checksum: Digest
    payload: Annotated[str, Field(min_length=2)]


class ContinuityFence(PortfolioModel):
    """Loss evidence after a checkpoint; cannot advance its durable bar boundary."""
    checkpoint_id: Identifier
    watermark: AwareDatetime
    generation: Count
    reason: SafeReason
    observed_at: AwareDatetime


class PersistenceSnapshot(PortfolioModel):
    enabled: bool
    status: PersistenceStatus
    reason: SafeReason | None = None
    database_healthy: bool
    session_id: Identifier | None = None
    session_created_at: AwareDatetime | None = None
    recovered: bool = False
    schema_version: Literal[1] = SCHEMA_VERSION
    durable_boundary: AwareDatetime | None = None
    checkpoint_at: AwareDatetime | None = None
    checkpoint_id: Identifier | None = None
    checksum: Digest | None = None
    retained_checkpoints: Count = 0
    retained_audit_events: Count = 0
    in_memory_boundary: AwareDatetime | None = None
    has_uncommitted_changes: bool = False
    configuration_compatible: bool | None = None
