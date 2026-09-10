"""Incremental independent signal horizons; future bars never feed decisions."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.application.backtest_identity import DatasetIdentity, outcome_identity, settings_identity
from src.application.backtest_math import arithmetic, outcome_returns
from src.application.backtest_settings import BacktestSettings
from src.application.historical_bars import symbols_for_replay, validate_bar
from src.application.historical_replay import DecisionCapture
from src.domain.backtesting import BacktestOutcomeStatus, BacktestSignalOutcome, HistoricalDecision, OutcomeReason
from src.domain.decisions import DecisionOutcome
from src.domain.market_data import KlineEvent
from src.domain.strategies import StrategyDirection


@dataclass
class _Pending:
    observation: HistoricalDecision
    next_open: datetime
    evidence: DatasetIdentity = field(default_factory=DatasetIdentity)
    bars_seen: int = 0
    entry_time: datetime | None = None
    entry_price: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None


class BacktestEvaluator:
    """Call advance(bar), then accept(the decision produced by that closed bar).

    Horizons overlap independently. At most H pending decisions per symbol are
    needed under the one-decision-per-bar replay convention; dedupe is run-local.
    Completed records are returned to the caller, not retained in this service.
    """

    def __init__(self, *, symbols: Sequence[str], interval: str = "1m",
                 settings: BacktestSettings | None = None) -> None:
        self.symbols = symbols_for_replay(symbols)
        self.interval = interval
        self.settings = BacktestSettings.model_validate(settings) if settings is not None else BacktestSettings()
        self.settings_id = settings_identity(self.settings)
        self._pending: dict[str, list[_Pending]] = {symbol: [] for symbol in self.symbols}
        self._latest: dict[str, KlineEvent] = {}
        self._key: tuple[datetime, str] | None = None
        self._capture = DecisionCapture()
        self._finished = False

    @property
    def duplicate_reads(self) -> int:
        return self._capture.duplicate_reads

    @property
    def pending_count(self) -> int:
        return sum(map(len, self._pending.values()))

    def advance(self, event: KlineEvent) -> tuple[BacktestSignalOutcome, ...]:
        if self._finished:
            raise RuntimeError("evaluator has finished")
        event = validate_bar(event)
        if event.symbol not in self._pending or event.interval != self.interval:
            raise ValueError("evaluator symbol or interval mismatch")
        key = (event.event_time, event.symbol)
        if self._key is not None and key <= self._key:
            raise ValueError("evaluator requires unique chronological (time, symbol) order")
        self._key = key
        self._latest[event.symbol] = event
        completed, remaining = [], []
        for pending in self._pending[event.symbol]:
            if event.open_time > pending.next_open:
                reason = OutcomeReason.MISSING_ENTRY_BAR if pending.bars_seen == 0 else OutcomeReason.MISSING_HORIZON_BAR
                completed.append(self._record(pending, reason=reason))
                continue
            if event.open_time < pending.next_open:
                raise ValueError("horizon bar precedes its expected interval")
            if pending.bars_seen == 0:
                pending.entry_time, pending.entry_price = event.open_time, event.open
            pending.bars_seen += 1
            pending.evidence.add(event)
            pending.high = event.high if pending.high is None else max(pending.high, event.high)
            pending.low = event.low if pending.low is None else min(pending.low, event.low)
            pending.next_open = event.close_time
            if pending.bars_seen == self.settings.holding_period_bars:
                completed.append(self._record(pending, exit_bar=event, reason=OutcomeReason.HORIZON_COMPLETED))
            else:
                remaining.append(pending)
        self._pending[event.symbol] = remaining
        return tuple(completed)

    def accept(self, observation: HistoricalDecision) -> bool:
        if self._finished:
            raise RuntimeError("evaluator has finished")
        observation = HistoricalDecision.model_validate(observation)
        decision = observation.decision
        event = self._latest.get(decision.symbol)
        if (event is None or event.open_time != observation.source_bar_open_time
                or event.close_time != observation.source_bar_close_time
                or decision.generated_at != event.close_time):
            raise ValueError("decision must describe the current finalized bar at replay time")
        if not self._capture.add(observation):
            return False
        if decision.outcome == DecisionOutcome.ELIGIBLE:
            pending = _Pending(observation, event.close_time)
            pending.evidence.add(event)
            self._pending[event.symbol].append(pending)
        return True

    def finish(self) -> tuple[BacktestSignalOutcome, ...]:
        outcomes = tuple(self._record(pending,
            reason=OutcomeReason.MISSING_ENTRY_BAR if pending.bars_seen == 0 else OutcomeReason.DATASET_ENDED)
            for symbol in self.symbols for pending in self._pending[symbol])
        for pending in self._pending.values():
            pending.clear()
        self._finished = True
        return outcomes

    @arithmetic
    def _record(self, pending: _Pending, *, reason: OutcomeReason,
                exit_bar: KlineEvent | None = None) -> BacktestSignalOutcome:
        observation, decision = pending.observation, pending.observation.decision
        status = BacktestOutcomeStatus.COMPLETED if exit_bar is not None else BacktestOutcomeStatus.INCOMPLETE
        favorable = adverse = returns = None
        if exit_bar is not None:
            entry = pending.entry_price
            returns = outcome_returns(entry, exit_bar.close, decision.direction, self.settings)
            if decision.direction == StrategyDirection.LONG:
                favorable, adverse = max(Decimal(0), (pending.high - entry) / entry), min(Decimal(0), (pending.low - entry) / entry)
            else:
                favorable, adverse = max(Decimal(0), (entry - pending.low) / entry), min(Decimal(0), (entry - pending.high) / entry)
        return BacktestSignalOutcome(outcome_id=outcome_identity(decision.decision_id, self.settings_id,
                observation.source_bar_open_time, pending.evidence.value, status, reason),
            decision_id=decision.decision_id, observation_id=decision.observation_id,
            symbol=decision.symbol, interval=self.interval, direction=decision.direction,
            decision_time=decision.generated_at, source_bar_open_time=observation.source_bar_open_time,
            holding_period_bars=self.settings.holding_period_bars, backtest_settings_id=self.settings_id,
            entry_time=pending.entry_time, entry_price_raw=pending.entry_price,
            exit_time=exit_bar.close_time if exit_bar else None, exit_price_raw=exit_bar.close if exit_bar else None,
            returns=returns, favorable_excursion=favorable, adverse_excursion=adverse, status=status, reason=reason)
