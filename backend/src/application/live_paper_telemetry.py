"""Read-only immutable dashboard projections; calculations remain in engines."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime

from src.application.backtest_math import arithmetic
from src.application.backtest_settings import BacktestSettings
from src.application.decision_settings import DecisionSettings
from src.application.decision_identity import policy_identity
from src.application.feature_settings import FeatureSettings
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.market_data_hub import MarketStatus, StreamFreshness
from src.application.paper_portfolio_math import marked_pnl
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.application.strategy_settings import StrategySettings
from src.domain.backtesting import Count
from src.domain.decisions import DecisionOutcome
from src.domain.features import Readiness
from src.domain.live_paper import LiveAnalysis, LiveClose, LivePaperEvent, LivePaperStatus, LivePosition
from src.domain.market_data import BookTickerEvent, KlineEvent, MarkPriceEvent, MarketSymbol, SafeReason, TradeEvent
from src.domain.models import Identifier
from src.domain.paper_portfolio import PaperEntryReservation, PaperPnl, PaperPortfolioCurvePoint, PaperPortfolioState, PortfolioModel
from src.domain.strategies import StrategyReadiness
from src.domain.paper_persistence import PersistenceSnapshot
from src.strategies.identity import identity


class LiveConfigurationIds(PortfolioModel):
    runtime: Identifier
    features: Identifier
    strategies: Identifier
    decisions: Identifier
    portfolio: Identifier
    costs: Identifier


class LiveConfiguration(PortfolioModel):
    identities: LiveConfigurationIds
    runtime: LivePaperSettings
    features: FeatureSettings
    strategies: StrategySettings
    decisions: DecisionSettings
    portfolio: PaperPortfolioSettings
    costs: BacktestSettings
    analytical_view: Literal['finalized_candles_only'] = 'finalized_candles_only'


class LiveSymbolSummary(PortfolioModel):
    symbol: MarketSymbol
    boundary: AwareDatetime | None
    closed_candles: Count
    feature_state: Readiness
    strategy_state: StrategyReadiness
    decision_outcome: DecisionOutcome | None


class LiveStatusSnapshot(PortfolioModel):
    mode: Literal['paper'] = 'paper'
    engine_version: Literal['live-paper-v1'] = 'live-paper-v1'
    as_of: AwareDatetime
    status: LivePaperStatus
    reasons: tuple[SafeReason, ...]
    running: bool
    started_at: AwareDatetime | None
    latest_update_at: AwareDatetime | None
    subscriber_dropped_events: Count
    last_boundary: AwareDatetime | None
    interval: str
    symbols: tuple[LiveSymbolSummary, ...]
    counters: dict[SafeReason, Count]
    configuration: LiveConfiguration
    market: MarketStatus
    persistence: PersistenceSnapshot


class LivePortfolioSnapshot(PortfolioModel):
    as_of: AwareDatetime
    valuation_as_of: AwareDatetime | None
    valuation_complete: bool
    state: PaperPortfolioState
    initial_virtual_equity: Decimal
    closed_pnl: PaperPnl
    outstanding_entry_fee_cost: Decimal
    outstanding_entry_slippage_cost: Decimal
    opened_count: Count
    completed_count: Count
    expired_reservations: Count


class LivePositionsSnapshot(PortfolioModel):
    as_of: AwareDatetime
    reservations: tuple[PaperEntryReservation, ...]
    active: tuple[LivePosition, ...]
    closed: tuple[LiveClose, ...]
    retained_closed_count: Count
    completed_count: Count


class LiveMarketSnapshot(PortfolioModel):
    """Current public observations, explicitly separate from captured decisions.

    Depth arrays are deliberately excluded. No last-value price is fabricated
    for an absent stream, and stream freshness accompanies every observation.
    """
    symbol: MarketSymbol
    as_of: AwareDatetime
    streams: dict[str, StreamFreshness]
    candle: KlineEvent | None
    trade: TradeEvent | None
    book_ticker: BookTickerEvent | None
    mark_price: MarkPriceEvent | None
    captured_analysis: LiveAnalysis | None


class LiveDashboardSnapshot(PortfolioModel):
    as_of: AwareDatetime
    status: LiveStatusSnapshot
    portfolio: LivePortfolioSnapshot
    positions: LivePositionsSnapshot
    market: tuple[LiveMarketSnapshot, ...]
    decisions: tuple[LiveAnalysis, ...]
    events: tuple[LivePaperEvent, ...]
    curve: tuple[PaperPortfolioCurvePoint, ...]


def status_snapshot(runtime: LivePaperCoordinator, as_of: datetime | None = None) -> LiveStatusSnapshot:
    state, reasons = runtime.health()
    summaries = []
    for symbol in runtime.batcher.symbols:
        item = runtime.latest_analyses.get(symbol)
        summaries.append(LiveSymbolSummary(symbol=symbol, boundary=item.boundary if item else None,
            closed_candles=item.features.closed_candles if item else 0,
            feature_state=item.features.state if item else Readiness.UNAVAILABLE,
            strategy_state=item.strategy.readiness if item else StrategyReadiness.UNAVAILABLE,
            decision_outcome=item.portfolio.upstream.outcome if item else None))
    return LiveStatusSnapshot(as_of=as_of or runtime.clock.now(), status=state, reasons=reasons, running=runtime.running,
        started_at=runtime.started_at, latest_update_at=runtime.events[-1].timestamp if runtime.events else None,
        subscriber_dropped_events=runtime._drops,
        persistence=runtime.persistence.snapshot(runtime.portfolio.last_boundary),
        last_boundary=runtime.portfolio.last_boundary, interval=runtime.batcher.interval, symbols=tuple(summaries),
        counters=dict(sorted(runtime.counts.items())), market=runtime.hub.status(), configuration=LiveConfiguration(
            runtime=runtime.settings, features=runtime.feature_settings, strategies=runtime.strategy_settings,
            decisions=runtime.decision_settings, portfolio=runtime.portfolio.policy.settings, costs=runtime.portfolio.costs,
            identities=LiveConfigurationIds(runtime=identity('live_settings', runtime.settings),
                features=identity('feature_settings', runtime.feature_settings),
                strategies=identity('settings', runtime.strategy_settings),
                decisions=policy_identity(runtime.decision_settings, runtime.batcher.symbols),
                portfolio=runtime.portfolio.policy.policy_id, costs=runtime.portfolio.cost_id)))


@arithmetic
def portfolio_snapshot(runtime: LivePaperCoordinator, as_of: datetime | None = None) -> LivePortfolioSnapshot:
    book = runtime.portfolio
    fees = slips = Decimal(0)
    for position in book.active.values():
        costs = marked_pnl(position.reservation.virtual_notional, position.entry_price_raw,
            position.entry_price_raw, position.reservation.direction, book.costs)
        fees += costs.fee_cost
        slips += costs.slippage_cost
    now = as_of or runtime.clock.now()
    state = book.state(book.last_boundary or now)
    return LivePortfolioSnapshot(as_of=now, valuation_as_of=book.last_boundary,
        valuation_complete=state.marked_equity is not None, state=state, initial_virtual_equity=book.policy.settings.initial_virtual_equity,
        closed_pnl=book.closed_pnl, outstanding_entry_fee_cost=fees, outstanding_entry_slippage_cost=slips,
        opened_count=book.opened_count, completed_count=book.completed_count, expired_reservations=book.expired_count)


def positions_snapshot(runtime: LivePaperCoordinator, limit: int, as_of: datetime | None = None) -> LivePositionsSnapshot:
    book = runtime.portfolio
    return LivePositionsSnapshot(as_of=as_of or runtime.clock.now(),
        reservations=tuple(item for _, item in sorted(book.pending.items())), active=book.positions(),
        closed=tuple(reversed(tuple(book.closes)[-limit:])), retained_closed_count=len(book.closes), completed_count=book.completed_count)


def dashboard_snapshot(runtime: LivePaperCoordinator, limit: int = 100) -> LiveDashboardSnapshot:
    """One event-loop transaction: no await, queue draining or engine evaluation.

    Models copy mutable dictionaries. Ledger transitions and analysis publication
    also run without suspension, so HTTP cannot observe half a close transition.
    Current feed observations retain their own time/generation; captured_analysis
    is explicitly historical and retains the admitted source generation.
    """
    now = runtime.clock.now()
    market = []
    for symbol in runtime.batcher.symbols:
        latest = runtime.hub.latest(symbol)
        market.append(LiveMarketSnapshot(symbol=symbol, as_of=latest.as_of, streams=latest.streams,
            candle=latest.events.get(f'kline:{runtime.batcher.interval}'), trade=latest.events.get('trade'),
            book_ticker=latest.events.get('book_ticker'), mark_price=latest.events.get('mark_price'),
            captured_analysis=runtime.latest_analyses.get(symbol)))
    return LiveDashboardSnapshot(as_of=now, status=status_snapshot(runtime, now),
        portfolio=portfolio_snapshot(runtime, now), positions=positions_snapshot(runtime, limit, now),
        market=tuple(market), decisions=tuple(reversed(tuple(runtime.decisions)[-limit:])),
        events=tuple(reversed(tuple(runtime.events)[-limit:])), curve=tuple(runtime.portfolio.curve)[-limit:])
