"""Pure all-or-none reservation policy and deterministic simultaneous arbitration."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.application.backtest_math import arithmetic
from src.application.paper_portfolio_identity import portfolio_policy_identity
from src.application.paper_portfolio_math import capacity_reason, desired_notional, portfolio_state
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.decisions import DecisionRecord
from src.domain.paper_portfolio import (
    PaperEntryReservation, PaperExposure, PaperPortfolioState, PortfolioAction,
    PortfolioDecisionRecord, PortfolioReason as Reason,
)
from src.strategies.identity import identity


def aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@arithmetic
def arbitration_key(decision: DecisionRecord) -> tuple:
    decision = DecisionRecord.model_validate(decision)
    return (-abs(decision.composite_score or Decimal(0)), -(decision.confidence or Decimal(0)),
            -(decision.agreement or Decimal(0)), decision.symbol, decision.decision_id)


@dataclass(frozen=True)
class PortfolioArbitration:
    decisions: tuple[PortfolioDecisionRecord, ...]
    reservations: tuple[PaperEntryReservation, ...]
    state: PaperPortfolioState
    duplicate_reads: int = 0


class PaperPortfolioPolicy:
    def __init__(self, settings: PaperPortfolioSettings | None = None) -> None:
        self.settings = PaperPortfolioSettings.model_validate(settings) if settings is not None else PaperPortfolioSettings()
        self.policy_id = portfolio_policy_identity(self.settings)

    @arithmetic
    def evaluate(self, decision: DecisionRecord, state: PaperPortfolioState, *, now: datetime,
                 duplicate: bool = False) -> PortfolioDecisionRecord:
        if not aware(now) or not aware(decision.generated_at) or not aware(state.timestamp):
            raise ValueError("portfolio evaluation requires aware datetime objects")
        decision, state = DecisionRecord.model_validate(decision), PaperPortfolioState.model_validate(state)
        notional = None
        if duplicate:
            reason = Reason.DUPLICATE_DECISION
        elif decision.outcome != "ELIGIBLE":
            reason = Reason.DECISION_NOT_ELIGIBLE
        elif state.timestamp != now or decision.generated_at != now or state.marked_equity is None:
            reason = Reason.INVALID_STATE
        elif state.marked_equity <= 0:
            reason = Reason.NONPOSITIVE_EQUITY
        else:
            notional = desired_notional(state.marked_equity, self.settings)
            reason = capacity_reason(state, decision.symbol, notional, self.settings) or Reason.CAPACITY_RESERVED
        action = (PortfolioAction.RESERVED if reason == Reason.CAPACITY_RESERVED else
                  PortfolioAction.IGNORED if reason in (Reason.DUPLICATE_DECISION, Reason.DECISION_NOT_ELIGIBLE)
                  else PortfolioAction.REJECTED)
        reservation_id = identity("paper_reservation", (self.policy_id, decision.decision_id, now, notional)) if action == PortfolioAction.RESERVED else None
        state_id = identity("portfolio_state", state)
        return PortfolioDecisionRecord(portfolio_decision_id=identity("portfolio_decision",
            (self.policy_id, decision.decision_id, state_id, action, reason)), upstream=decision,
            policy_id=self.policy_id, state_id=state_id, evaluated_at=now, action=action, reason=reason,
            desired_notional=notional, reservation_id=reservation_id)

    @arithmetic
    def arbitrate(self, decisions: Iterable[DecisionRecord], state: PaperPortfolioState,
                  *, now: datetime) -> PortfolioArbitration:
        """Reserve in score/confidence/agreement/symbol/ID order without changing equity.

        Exact duplicate reads are counted once. Conflicting reuse fails closed.
        The ledger separately owns cross-timestamp run-local identity suppression.
        """
        if not aware(now) or not aware(state.timestamp):
            raise ValueError("arbitration requires aware datetime objects")
        state = PaperPortfolioState.model_validate(state)
        unique: dict[str, DecisionRecord] = {}
        duplicates = 0
        for raw in decisions:
            decision = DecisionRecord.model_validate(raw)
            if not aware(raw.generated_at) or decision.generated_at != now:
                raise ValueError("arbitration requires one current decision timestamp")
            if previous := unique.get(decision.decision_id):
                if previous != decision:
                    raise ValueError("conflicting simultaneous decision identity")
                duplicates += 1
            else:
                unique[decision.decision_id] = decision
        records, reservations = [], []
        for decision in sorted(unique.values(), key=arbitration_key):
            record = self.evaluate(decision, state, now=now)
            records.append(record)
            if record.action != PortfolioAction.RESERVED:
                continue
            reservation = PaperEntryReservation(reservation_id=record.reservation_id, decision_id=decision.decision_id,
                symbol=decision.symbol, direction=decision.direction, virtual_notional=record.desired_notional,
                decision_time=now, expected_entry_time=now, policy_id=self.policy_id)
            reservations.append(reservation)
            exposures = {item.symbol: item for item in state.exposures}
            exposures[decision.symbol] = PaperExposure(symbol=decision.symbol, reserved_notional=record.desired_notional,
                                                       reservation_count=1)
            state = portfolio_state(timestamp=state.timestamp, realized=state.realized_equity,
                unrealized=state.unrealized_net_pnl, peak=state.peak_equity, exposures=tuple(exposures.values()))
        return PortfolioArbitration(tuple(records), tuple(reservations), state, duplicates)
