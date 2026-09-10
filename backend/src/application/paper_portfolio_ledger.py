"""Finite-run virtual ledger: reservations, exact bars, marks and fixed exits."""

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from src.application.backtest_identity import DatasetIdentity, settings_identity
from src.application.backtest_math import arithmetic
from src.application.backtest_settings import BacktestSettings
from src.application.feature_history import next_open_time
from src.application.historical_bars import symbols_for_replay, validate_bar
from src.application.historical_replay import DecisionCapture
from src.application.paper_portfolio_math import closed_pnl, marked_pnl, portfolio_state
from src.application.paper_portfolio_policy import PaperPortfolioPolicy
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.backtesting import HistoricalDecision
from src.domain.market_data import KlineEvent
from src.domain.paper_portfolio import (
    PaperEntryReservation, PaperExposure, PaperPnl, PaperPortfolioCurvePoint, PaperPortfolioState,
    PaperPosition, PaperPositionClose, PaperReservationExpiry, PortfolioDecisionRecord,
)
from src.strategies.identity import identity


def zero_pnl() -> PaperPnl:
    return PaperPnl(gross_pnl=0, fee_cost=0, slippage_cost=0, total_cost=0, net_pnl=0)


class PaperPortfolioLedger:
    """Advance complete same-time groups, then finish once the finite input ends.

    Every group applies due entries, known close marks/exits, then arbitration.
    Unknown holding marks permanently invalidate total marked equity; other
    existing positions may still finish. No new reservation can pass that state.
    A failed advance invalidates the ledger; callers must not resume partial work.
    """

    def __init__(self, *, symbols: Sequence[str], interval: str = "1m",
                 settings: PaperPortfolioSettings | None = None, backtest_settings: BacktestSettings | None = None) -> None:
        self.symbols = symbols_for_replay(symbols)
        next_open_time(datetime(2000, 1, 1, tzinfo=timezone.utc), interval)
        self.interval = interval
        self.policy = PaperPortfolioPolicy(settings)
        self.backtest_settings = BacktestSettings.model_validate(backtest_settings) if backtest_settings is not None else BacktestSettings()
        self.backtest_settings_id = settings_identity(self.backtest_settings)
        self._capture = DecisionCapture()
        self._time: datetime | None = None
        self._peak = self.policy.settings.initial_virtual_equity
        self._closed = zero_pnl()
        self._pending: dict[str, PaperEntryReservation] = {}
        self._active: dict[str, str] = {}
        self._positions: dict[str, PaperPosition] = {}
        self._marks: dict[str, Decimal] = {}
        self._evidence: dict[str, DatasetIdentity] = {}
        self._reservations: list[PaperEntryReservation] = []
        self._expiries: list[PaperReservationExpiry] = []
        self._closes: list[PaperPositionClose] = []
        self._decisions: list[PortfolioDecisionRecord] = []
        self._curve: list[PaperPortfolioCurvePoint] = []
        self._finished = self._failed = False
        self._final: PaperPortfolioState | None = None

    @property
    def decisions(self) -> tuple[PortfolioDecisionRecord, ...]:
        return tuple(self._decisions)

    @property
    def reservations(self) -> tuple[PaperEntryReservation, ...]:
        return tuple(self._reservations)

    @property
    def expiries(self) -> tuple[PaperReservationExpiry, ...]:
        return tuple(self._expiries)

    @property
    def positions(self) -> tuple[PaperPosition, ...]:
        return tuple(self._positions.values())

    @property
    def closes(self) -> tuple[PaperPositionClose, ...]:
        return tuple(self._closes)

    @property
    def curve(self) -> tuple[PaperPortfolioCurvePoint, ...]:
        return tuple(self._curve)

    @property
    def duplicate_reads(self) -> int:
        return self._capture.duplicate_reads

    def advance(self, bars: Sequence[KlineEvent], observations: Sequence[HistoricalDecision] = ()) -> tuple[PortfolioDecisionRecord, ...]:
        if self._finished or self._failed:
            raise RuntimeError("ledger is finished or invalidated")
        try:
            return self._advance(bars, observations)
        except Exception:
            self._failed = True
            raise

    @arithmetic
    def _advance(self, bars: Sequence[KlineEvent], observations: Sequence[HistoricalDecision]) -> tuple[PortfolioDecisionRecord, ...]:
        events = tuple(sorted((validate_bar(bar) for bar in bars), key=lambda bar: bar.symbol))
        if not events or len({bar.event_time for bar in events}) != 1 or len({bar.symbol for bar in events}) != len(events):
            raise ValueError("ledger requires a nonempty unique same-time bar group")
        if any(bar.symbol not in self.symbols or bar.interval != self.interval for bar in events):
            raise ValueError("ledger bar scope mismatch")
        now = events[0].event_time
        if self._time is not None and now <= self._time:
            raise ValueError("ledger groups must increase chronologically")
        by_symbol = {bar.symbol: bar for bar in events}
        validated = tuple(HistoricalDecision.model_validate(item) for item in observations)
        for item in validated:
            bar = by_symbol.get(item.decision.symbol)
            if (bar is None or item.source_bar_open_time != bar.open_time
                    or item.source_bar_close_time != bar.close_time or item.decision.generated_at != now):
                raise ValueError("decision must describe a current finalized group bar")
        if self._time is None:
            self._curve.append(PaperPortfolioCurvePoint(state=self._snapshot(events[0].open_time),
                cumulative_closed_pnl=self._closed, open_count_before_exits=0))
        self._time = now
        self._enter_due(by_symbol, now)
        count_before_exits = len(self._active)
        self._mark_and_close(by_symbol, now)
        state = self._snapshot(now)
        decisions = [item.decision for item in validated if self._capture.add(item)]
        batch = self.policy.arbitrate(decisions, state, now=now)
        self._decisions.extend(batch.decisions)
        for reservation in batch.reservations:
            self._pending[reservation.symbol] = reservation
            self._reservations.append(reservation)
        self._curve.append(PaperPortfolioCurvePoint(state=batch.state, cumulative_closed_pnl=self._closed,
            open_count_before_exits=count_before_exits))
        return batch.decisions

    def _enter_due(self, bars: dict[str, KlineEvent], now: datetime) -> None:
        for symbol, reservation in sorted(tuple(self._pending.items())):
            if next_open_time(reservation.expected_entry_time, self.interval) > now:
                continue
            bar = bars.get(symbol)
            del self._pending[symbol]
            if bar is None or bar.open_time != reservation.expected_entry_time:
                self._expiries.append(PaperReservationExpiry(reservation_id=reservation.reservation_id,
                    observed_at=now, reason="missing_entry_bar"))
                continue
            key = identity("paper_position", (reservation.reservation_id, bar, self.backtest_settings_id))
            position = PaperPosition(position_id=key, reservation=reservation, interval=self.interval,
                entry_time=bar.open_time, entry_price_raw=bar.open, holding_period_bars=self.backtest_settings.holding_period_bars,
                bars_held=0, expected_next_open=bar.open_time, backtest_settings_id=self.backtest_settings_id)
            self._positions[key] = position
            self._active[symbol] = key
            self._evidence[key] = DatasetIdentity()

    def _mark_and_close(self, bars: dict[str, KlineEvent], now: datetime) -> None:
        for symbol, key in sorted(tuple(self._active.items())):
            position = self._positions[key]
            if position.status == "INCOMPLETE":
                continue
            bar = bars.get(symbol)
            if bar is None or bar.open_time != position.expected_next_open:
                self._positions[key] = PaperPosition.model_validate(position.model_copy(update={
                    "status": "INCOMPLETE", "reason": "missing_horizon_bar"}))
                self._marks.pop(key, None)
                self._evidence.pop(key, None)
                continue
            self._evidence[key].add(bar)
            held = position.bars_held + 1
            done = held == position.holding_period_bars
            position = PaperPosition.model_validate(position.model_copy(update={"bars_held": held,
                "expected_next_open": bar.close_time, "last_mark_time": now, "last_mark_price": bar.close,
                "status": "CLOSED" if done else "OPEN", "reason": "horizon_completed" if done else "holding"}))
            self._positions[key] = position
            if not done:
                self._marks[key] = marked_pnl(position.reservation.virtual_notional, position.entry_price_raw,
                    bar.close, position.reservation.direction, self.backtest_settings).net_pnl
                continue
            pnl = closed_pnl(position.reservation.virtual_notional, position.entry_price_raw,
                bar.close, position.reservation.direction, self.backtest_settings)
            self._closes.append(PaperPositionClose(close_id=identity("paper_close",
                (key, self._evidence[key].value, self.backtest_settings_id)), position_id=key,
                exit_time=now, exit_price_raw=bar.close, pnl=pnl))
            self._closed = PaperPnl(**{field: getattr(self._closed, field) + getattr(pnl, field) for field in PaperPnl.model_fields})
            del self._active[symbol]
            self._marks.pop(key, None)
            del self._evidence[key]

    @arithmetic
    def _snapshot(self, now: datetime) -> PaperPortfolioState:
        exposures = tuple(PaperExposure(symbol=symbol,
            open_notional=self._positions[self._active[symbol]].reservation.virtual_notional if symbol in self._active else 0,
            open_count=int(symbol in self._active),
            reserved_notional=self._pending[symbol].virtual_notional if symbol in self._pending else 0,
            reservation_count=int(symbol in self._pending)) for symbol in self.symbols)
        unknown = any(self._positions[key].status == "INCOMPLETE" for key in self._active.values())
        state = portfolio_state(timestamp=now, realized=self.policy.settings.initial_virtual_equity + self._closed.net_pnl,
            unrealized=None if unknown else sum(self._marks.values(), Decimal(0)), peak=self._peak, exposures=exposures)
        self._peak = state.peak_equity
        return state

    def finish(self) -> PaperPortfolioState | None:
        """Do not rewrite historical curve points using knowledge of dataset end."""
        if self._failed:
            raise RuntimeError("ledger is invalidated")
        if self._finished:
            return self._final
        if self._time is not None:
            for reservation in sorted(self._pending.values(), key=lambda item: item.symbol):
                self._expiries.append(PaperReservationExpiry(reservation_id=reservation.reservation_id,
                    observed_at=self._time, reason="dataset_ended"))
            self._pending.clear()
            for key in self._active.values():
                position = self._positions[key]
                if position.status == "OPEN":
                    self._positions[key] = PaperPosition.model_validate(position.model_copy(update={
                        "status": "INCOMPLETE", "reason": "dataset_ended"}))
            self._marks.clear()
            self._evidence.clear()
            self._final = self._snapshot(self._time)
        self._finished = True
        return self._final
