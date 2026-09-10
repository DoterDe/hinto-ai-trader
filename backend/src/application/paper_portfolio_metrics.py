"""Pure shared-capital metrics over finalized ledger artifacts; no fitting."""

from collections import Counter
from decimal import Decimal

from src.application.backtest_math import arithmetic
from src.application.backtest_settings import BacktestSettings
from src.application.paper_portfolio_math import marked_pnl
from src.domain.paper_portfolio import (
    PaperEntryReservation, PaperPnl, PaperPortfolioCurvePoint, PaperPortfolioMetrics,
    PaperPortfolioState, PaperPosition, PaperPositionClose, PaperReservationExpiry,
    PaperSymbolMetrics, PortfolioDecisionRecord, PortfolioRejectionCount,
)


@arithmetic
def sum_pnl(closes: tuple[PaperPositionClose, ...]) -> PaperPnl:
    return PaperPnl(**{field: sum((getattr(item.pnl, field) for item in closes), Decimal(0)) for field in PaperPnl.model_fields})


def unique(items, key):
    result = {getattr(item, key): item for item in items}
    if len(result) != len(items):
        raise ValueError("portfolio metrics require unique artifacts")
    return result


@arithmetic
def portfolio_metrics(*, initial_equity: Decimal, input_count: int,
                      decisions: tuple[PortfolioDecisionRecord, ...], reservations: tuple[PaperEntryReservation, ...],
                      expiries: tuple[PaperReservationExpiry, ...], positions: tuple[PaperPosition, ...],
                      closes: tuple[PaperPositionClose, ...], curve: tuple[PaperPortfolioCurvePoint, ...],
                      final_state: PaperPortfolioState | None, backtest_settings: BacktestSettings,
                      symbols: tuple[str, ...]) -> PaperPortfolioMetrics:
    """Closed PnL totals exclude open entry costs, which are reported separately.

    Drawdown/exposure maxima use known canonical close snapshots; unknown marks
    set valuation_complete=False. Average open count excludes the initial anchor.
    Peak open count also covers H=1 entries closed within a single step.
    """
    from pydantic import TypeAdapter
    from src.domain.market_data import PositiveDecimal
    initial = TypeAdapter(PositiveDecimal).validate_python(initial_equity)
    decisions = tuple(PortfolioDecisionRecord.model_validate(item) for item in decisions)
    reservations = tuple(PaperEntryReservation.model_validate(item) for item in reservations)
    expiries = tuple(PaperReservationExpiry.model_validate(item) for item in expiries)
    positions = tuple(PaperPosition.model_validate(item) for item in positions)
    closes = tuple(PaperPositionClose.model_validate(item) for item in closes)
    curve = tuple(PaperPortfolioCurvePoint.model_validate(item) for item in curve)
    final = PaperPortfolioState.model_validate(final_state) if final_state is not None else None
    costs = BacktestSettings.model_validate(backtest_settings)
    unique(decisions, 'portfolio_decision_id')
    if len({item.upstream.decision_id for item in decisions}) != len(decisions):
        raise ValueError("upstream decisions must be deduplicated")
    reservation_by_id, position_by_id = unique(reservations, 'reservation_id'), unique(positions, 'position_id')
    expiry_by_id, close_by_id = unique(expiries, 'reservation_id'), unique(closes, 'position_id')
    unique(closes, 'close_id')
    accepted = {item.reservation_id: item for item in decisions if item.action == 'RESERVED'}
    if set(accepted) != set(reservation_by_id):
        raise ValueError("reservations must match accepted decisions")
    for reservation in reservations:
        record = accepted[reservation.reservation_id]
        if (record.upstream.decision_id != reservation.decision_id or record.upstream.symbol != reservation.symbol
                or record.upstream.direction != reservation.direction or record.desired_notional != reservation.virtual_notional
                or record.policy_id != reservation.policy_id or record.evaluated_at != reservation.decision_time):
            raise ValueError("reservation provenance mismatch")
    entered = {item.reservation.reservation_id for item in positions}
    if len(entered) != len(positions) or entered & set(expiry_by_id) or entered | set(expiry_by_id) != set(reservation_by_id):
        raise ValueError("every reservation must open once or expire")
    for position in positions:
        if position.reservation != reservation_by_id[position.reservation.reservation_id] or position.status == 'OPEN':
            raise ValueError("metrics require finalized positions with matching reservations")
    if set(close_by_id) != {item.position_id for item in positions if item.status == 'CLOSED'}:
        raise ValueError("closes must match completed positions")
    for close in closes:
        position = position_by_id[close.position_id]
        if close.exit_time != position.last_mark_time or close.exit_price_raw != position.last_mark_price:
            raise ValueError("close evidence must match final position bar")
    if input_count == 0:
        if any((decisions, reservations, positions, expiries, closes, curve, final)):
            raise ValueError("empty input cannot have ledger artifacts")
    elif final is None or not curve:
        raise ValueError("nonempty input requires a finalized curve")
    ordered_closes = tuple(sorted(closes, key=lambda item: (item.exit_time, position_by_id[item.position_id].reservation.symbol, item.position_id)))
    total = sum_pnl(ordered_closes)
    realized = initial + total.net_pnl
    incomplete = tuple(item for item in positions if item.status == 'INCOMPLETE')
    if final is not None:
        if (final.realized_equity != realized or final.reservation_count != 0 or final.open_count != len(incomplete)
                or final.open_notional != sum((item.reservation.virtual_notional for item in incomplete), Decimal(0))
                or (incomplete and final.marked_equity is not None)):
            raise ValueError("final equity or unresolved exposure does not reconcile")
    previous = None
    peak, max_drawdown = initial, Decimal(0)
    close_index = 0
    cumulative = PaperPnl(gross_pnl=0, fee_cost=0, slippage_cost=0, total_cost=0, net_pnl=0)
    for point in curve:
        state = point.state
        if previous is not None and state.timestamp <= previous:
            raise ValueError("curve timestamps must increase")
        previous = state.timestamp
        while close_index < len(ordered_closes) and ordered_closes[close_index].exit_time <= state.timestamp:
            pnl = ordered_closes[close_index].pnl
            cumulative = PaperPnl(**{field: getattr(cumulative, field) + getattr(pnl, field) for field in PaperPnl.model_fields})
            close_index += 1
        if point.cumulative_closed_pnl != cumulative or state.realized_equity != initial + cumulative.net_pnl:
            raise ValueError("curve cumulative realized PnL must reconcile")
        if state.marked_equity is not None:
            peak = max(peak, state.marked_equity)
            max_drawdown = max(max_drawdown, state.drawdown)
        if state.peak_equity != peak:
            raise ValueError("curve equity peak must reconcile")
    if final is not None and (final.timestamp != previous or final.peak_equity != peak or cumulative != total):
        raise ValueError("final state must match curve history")
    rejected = Counter(item.reason for item in decisions if item.action == 'REJECTED')
    net = [item.pnl.net_pnl for item in ordered_closes]
    wins, losses = sum(value > 0 for value in net), sum(value < 0 for value in net)
    open_costs = tuple(marked_pnl(item.reservation.virtual_notional, item.entry_price_raw, item.entry_price_raw,
                                item.reservation.direction, costs) for item in incomplete)
    per_symbol = []
    for symbol in sorted(set(symbols) | {item.reservation.symbol for item in positions}):
        selected = tuple(item for item in positions if item.reservation.symbol == symbol)
        selected_ids = {item.position_id for item in selected}
        symbol_closes = tuple(item for item in ordered_closes if item.position_id in selected_ids)
        per_symbol.append(PaperSymbolMetrics(symbol=symbol, opened_count=len(selected), completed_count=len(symbol_closes),
            incomplete_count=sum(item.status == 'INCOMPLETE' for item in selected), closed_pnl=sum_pnl(symbol_closes)))
    known_equities = [item.state.marked_equity for item in curve if item.state.marked_equity is not None]
    return PaperPortfolioMetrics(input_bar_count=input_count, evaluated_decision_count=len(decisions),
        upstream_eligible_count=sum(item.upstream.outcome == 'ELIGIBLE' for item in decisions),
        upstream_blocked_count=sum(item.upstream.outcome == 'BLOCKED' for item in decisions),
        upstream_no_action_count=sum(item.upstream.outcome == 'NO_ACTION' for item in decisions),
        reserved_count=len(reservations), rejected_count=sum(rejected.values()),
        ignored_count=sum(item.action == 'IGNORED' for item in decisions), opened_count=len(positions),
        completed_count=len(closes), incomplete_count=len(incomplete), missing_entry_reservation_count=len(expiries),
        long_opened_count=sum(item.reservation.direction == 'LONG' for item in positions),
        short_opened_count=sum(item.reservation.direction == 'SHORT' for item in positions),
        initial_virtual_equity=initial, final_realized_equity=realized,
        final_marked_equity=final.marked_equity if final is not None else initial, total_closed_pnl=total,
        outstanding_entry_fee_cost=sum((item.fee_cost for item in open_costs), Decimal(0)),
        outstanding_entry_slippage_cost=sum((item.slippage_cost for item in open_costs), Decimal(0)),
        realized_total_return=total.net_pnl/initial, peak_equity=peak, max_drawdown=max_drawdown,
        max_gross_exposure=max((item.state.gross_exposure for item in curve), default=Decimal(0)),
        max_observed_gross_exposure_fraction=max((item.state.gross_exposure_fraction for item in curve
            if item.state.gross_exposure_fraction is not None), default=Decimal(0)),
        max_simultaneous_open_positions=max((item.open_count_before_exits for item in curve), default=0),
        average_open_count=Decimal(sum(item.state.open_count for item in curve[1:]))/(len(curve)-1) if len(curve)>1 else Decimal(0),
        turnover=sum((item.reservation.virtual_notional for item in positions), Decimal(0))/initial,
        win_count=wins, loss_count=losses, flat_count=len(net)-wins-losses,
        win_rate=Decimal(wins)/(wins+losses) if wins+losses else None,
        valuation_complete=not incomplete and all(item.state.marked_equity is not None for item in curve),
        nonpositive_equity_observed=realized <= 0 or any(value <= 0 for value in known_equities),
        per_symbol=tuple(per_symbol), rejection_counts=tuple(PortfolioRejectionCount(reason=reason, count=count)
            for reason, count in sorted(rejected.items())))
