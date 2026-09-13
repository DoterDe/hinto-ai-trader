"""Bounded live ledger, reusing Phase 7 policy, domain and pure accounting."""

from collections import OrderedDict, deque
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from src.application.backtest_identity import DatasetIdentity, settings_identity
from src.application.backtest_math import arithmetic
from src.application.backtest_settings import BacktestSettings
from src.application.feature_history import next_open_time
from src.application.historical_bars import symbols_for_replay, validate_bar
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_portfolio_ledger import zero_pnl
from src.application.paper_portfolio_math import closed_pnl, marked_pnl, portfolio_state
from src.application.paper_portfolio_policy import PaperPortfolioPolicy
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.decisions import DecisionRecord
from src.domain.live_paper import LiveClose, LivePosition
from src.domain.market_data import KlineEvent
from src.domain.paper_portfolio import (
    PaperExposure, PaperPnl, PaperPortfolioCurvePoint, PaperPortfolioState,
    PaperPosition, PaperPositionClose, PaperEntryReservation, PortfolioDecisionRecord,
)
from src.strategies.identity import identity


class LivePaperPortfolio:
    def __init__(self, symbols: Sequence[str], *, interval: str, runtime: LivePaperSettings,
                 settings: PaperPortfolioSettings, costs: BacktestSettings) -> None:
        self.symbols = symbols_for_replay(symbols)
        self.interval = interval
        self.policy = PaperPortfolioPolicy(settings)
        self.costs = BacktestSettings.model_validate(costs)
        self.cost_id = settings_identity(self.costs)
        self.runtime = LivePaperSettings.model_validate(runtime)
        self.pending: dict[str, PaperEntryReservation] = {}
        self.active: dict[str, PaperPosition] = {}
        self.marks: dict[str, Decimal] = {}
        self.evidence: dict[str, DatasetIdentity] = {}
        self.closes: deque[LiveClose] = deque(maxlen=runtime.position_history_limit)
        self.curve: deque[PaperPortfolioCurvePoint] = deque(maxlen=runtime.curve_history_limit)
        self.closed_pnl = zero_pnl()
        self.peak = settings.initial_virtual_equity
        self.last_boundary: datetime | None = None
        self._seen: OrderedDict[str, str] = OrderedDict()
        self._failed = False
        self.expired_count = self.opened_count = self.completed_count = self.duplicate_count = 0

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    def next_required_boundary(self) -> datetime | None:
        opens = [item.expected_entry_time for item in self.pending.values()]
        opens.extend(item.expected_next_open for item in self.active.values() if item.status == 'OPEN')
        return min((next_open_time(value, self.interval) for value in opens), default=None)

    def invalidate(self) -> None:
        """Observation loss cannot be repaired by later marks or cached prices."""
        self.expired_count += len(self.pending)
        self.pending.clear()
        for symbol, item in tuple(self.active.items()):
            if item.status == 'OPEN':
                self.active[symbol] = PaperPosition.model_validate(item.model_copy(update={
                    'status': 'INCOMPLETE', 'reason': 'missing_horizon_bar'}))
        self.marks.clear()
        self.evidence.clear()

    def positions(self) -> tuple[LivePosition, ...]:
        return tuple(LivePosition(position=item, unrealized_net_pnl=self.marks.get(symbol))
                     for symbol, item in sorted(self.active.items()))

    @arithmetic
    def state(self, timestamp: datetime) -> PaperPortfolioState:
        exposures = tuple(PaperExposure(symbol=symbol,
            open_notional=self.active[symbol].reservation.virtual_notional if symbol in self.active else 0,
            open_count=int(symbol in self.active),
            reserved_notional=self.pending[symbol].virtual_notional if symbol in self.pending else 0,
            reservation_count=int(symbol in self.pending)) for symbol in self.symbols)
        unknown = self._failed or any(item.status == 'INCOMPLETE' for item in self.active.values())
        return portfolio_state(timestamp=timestamp, realized=self.policy.settings.initial_virtual_equity+self.closed_pnl.net_pnl,
            unrealized=None if unknown else sum(self.marks.values(), Decimal(0)), peak=self.peak, exposures=exposures)

    def advance(self, boundary: datetime, bars: Sequence[KlineEvent], decisions: Sequence[DecisionRecord] = ()) -> tuple[PortfolioDecisionRecord, ...]:
        if self._failed:
            raise RuntimeError('live portfolio is invalidated')
        try:
            return self._advance(boundary, bars, decisions)
        except Exception:
            self._failed = True
            raise

    @arithmetic
    def _advance(self, boundary: datetime, bars: Sequence[KlineEvent], decisions: Sequence[DecisionRecord]) -> tuple[PortfolioDecisionRecord, ...]:
        events = tuple(validate_bar(bar) for bar in bars)
        by_symbol = {bar.symbol: bar for bar in events}
        if (len(by_symbol) != len(events) or any(bar.close_time != boundary or bar.symbol not in self.symbols
                or bar.interval != self.interval for bar in events)):
            raise ValueError('live portfolio requires one scoped close group')
        if self.last_boundary is not None and boundary <= self.last_boundary:
            raise ValueError('live portfolio boundary must increase')
        validated = tuple(DecisionRecord.model_validate(item) for item in decisions)
        if any(item.symbol not in by_symbol or item.generated_at != boundary for item in validated):
            raise ValueError('live decisions must describe the current close group')
        if self.last_boundary is None:
            initial_time = min((bar.open_time for bar in events), default=boundary)
            self.curve.append(PaperPortfolioCurvePoint(state=self.state(initial_time),
                cumulative_closed_pnl=self.closed_pnl, open_count_before_exits=0))
        self.last_boundary = boundary
        for symbol, reservation in sorted(tuple(self.pending.items())):
            if next_open_time(reservation.expected_entry_time, self.interval) > boundary:
                continue
            del self.pending[symbol]
            bar = by_symbol.get(symbol)
            if bar is None or bar.open_time != reservation.expected_entry_time:
                self.expired_count += 1
                continue
            key = identity('paper_position', (reservation.reservation_id, bar, self.cost_id))
            self.active[symbol] = PaperPosition(position_id=key, reservation=reservation, interval=self.interval,
                entry_time=bar.open_time, entry_price_raw=bar.open, holding_period_bars=self.costs.holding_period_bars,
                bars_held=0, expected_next_open=bar.open_time, backtest_settings_id=self.cost_id)
            self.evidence[symbol] = DatasetIdentity()
            self.opened_count += 1
        before_exits = len(self.active)
        for symbol, position in sorted(tuple(self.active.items())):
            if position.status == 'INCOMPLETE':
                continue
            bar = by_symbol.get(symbol)
            if bar is None or bar.open_time != position.expected_next_open:
                self.active[symbol] = PaperPosition.model_validate(position.model_copy(update={
                    'status': 'INCOMPLETE', 'reason': 'missing_horizon_bar'}))
                self.marks.pop(symbol, None)
                self.evidence.pop(symbol, None)
                continue
            self.evidence[symbol].add(bar)
            held = position.bars_held + 1
            done = held == position.holding_period_bars
            position = PaperPosition.model_validate(position.model_copy(update={'bars_held': held,
                'expected_next_open': boundary, 'last_mark_time': boundary, 'last_mark_price': bar.close,
                'status': 'CLOSED' if done else 'OPEN', 'reason': 'horizon_completed' if done else 'holding'}))
            self.active[symbol] = position
            if done:
                pnl = closed_pnl(position.reservation.virtual_notional, position.entry_price_raw, bar.close,
                                 position.reservation.direction, self.costs)
                close = PaperPositionClose(close_id=identity('paper_close',
                    (position.position_id, self.evidence[symbol].value, self.cost_id)),
                    position_id=position.position_id, exit_time=boundary, exit_price_raw=bar.close, pnl=pnl)
                self.closes.append(LiveClose(position=position, close=close))
                self.closed_pnl = PaperPnl(**{name: getattr(self.closed_pnl, name)+getattr(pnl, name)
                                             for name in PaperPnl.model_fields})
                self.completed_count += 1
                del self.active[symbol]
                self.marks.pop(symbol, None)
                del self.evidence[symbol]
            else:
                self.marks[symbol] = marked_pnl(position.reservation.virtual_notional, position.entry_price_raw,
                    bar.close, position.reservation.direction, self.costs).net_pnl
        unique = []
        for decision in validated:
            fingerprint = identity('live_decision', decision)
            previous = self._seen.get(decision.decision_id)
            if previous is not None:
                if previous != fingerprint:
                    raise ValueError('conflicting live decision identity')
                self.duplicate_count += 1
                continue
            unique.append(decision)
            self._seen[decision.decision_id] = fingerprint
            while len(self._seen) > self.runtime.event_history_limit:
                self._seen.popitem(last=False)
        state = self.state(boundary)
        self.peak = state.peak_equity
        result = self.policy.arbitrate(unique, state, now=boundary)
        self.pending.update((item.symbol, item) for item in result.reservations)
        self.curve.append(PaperPortfolioCurvePoint(state=result.state, cumulative_closed_pnl=self.closed_pnl,
            open_count_before_exits=before_exits))
        return result.decisions
