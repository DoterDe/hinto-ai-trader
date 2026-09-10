"""Pure signal-level statistics; no capital allocation or policy optimization."""

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from src.application.backtest_math import arithmetic
from src.application.feature_history import next_open_time
from src.domain.backtesting import (
    BacktestCohortMetrics, BacktestMetrics, BacktestSignalOutcome, BacktestTimeSegment,
    HistoricalDecision, NormalizedCurvePoint,
)
from src.domain.decisions import DecisionOutcome
from src.domain.strategies import StrategyDirection


def expected_exit_time(outcome: BacktestSignalOutcome) -> datetime:
    count, unit = int(outcome.interval[:-1]), outcome.interval[-1]
    return next_open_time(outcome.decision_time, f"{count * outcome.holding_period_bars}{unit}")


def _validated(observations: Iterable[HistoricalDecision], outcomes: Iterable[BacktestSignalOutcome]):
    observations = tuple(HistoricalDecision.model_validate(item) for item in observations)
    outcomes = tuple(BacktestSignalOutcome.model_validate(item) for item in outcomes)
    decisions = {item.decision.decision_id: item for item in observations}
    if len(decisions) != len(observations):
        raise ValueError("metrics require unique captured decisions")
    ids = {item.decision_id for item in outcomes}
    if len(ids) != len(outcomes) or len({item.outcome_id for item in outcomes}) != len(outcomes):
        raise ValueError("metrics require unique signal outcomes")
    if ids != {key for key, item in decisions.items() if item.decision.outcome == DecisionOutcome.ELIGIBLE}:
        raise ValueError("outcomes must correspond exactly to eligible decisions")
    for item in outcomes:
        observation = decisions[item.decision_id]
        decision = observation.decision
        if (item.symbol != decision.symbol or item.direction != decision.direction
                or item.observation_id != decision.observation_id or item.decision_time != decision.generated_at
                or item.source_bar_open_time != observation.source_bar_open_time
                or (item.entry_time is not None and item.entry_time != observation.source_bar_close_time)
                or (item.exit_time is not None and item.exit_time != expected_exit_time(item))):
            raise ValueError("outcome provenance or horizon does not match its decision")
    return observations, outcomes


@arithmetic
def calculate_metrics(observations: Iterable[HistoricalDecision], outcomes: Iterable[BacktestSignalOutcome],
                      *, cutoff: datetime | None = None) -> BacktestMetrics:
    """Order completed signals by (exit, decision time, symbol, decision ID).

    Win rate excludes flats. Gross profit/loss sum positive/negative *net* signal
    returns, distinct from pre-cost sum_gross_returns. Curve=1+sum(net), with
    drawdown=(running_peak-curve)/running_peak; it can exceed 100% and is not an
    account curve. Fixed segment cutoffs censor every horizon extending past it,
    irrespective of whether future observations eventually complete that signal.
    """
    observations, outcomes = _validated(observations, outcomes)
    if cutoff is not None:
        if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("metric cutoff must be aware")
        if any(item.decision.generated_at > cutoff for item in observations):
            raise ValueError("metric cutoff cannot precede its sampled decisions")
    censored = {item.decision_id for item in outcomes
                if cutoff is not None and expected_exit_time(item) > cutoff}
    completed = sorted((item for item in outcomes if item.status == "COMPLETED" and item.decision_id not in censored),
        key=lambda item: (item.exit_time, item.decision_time, item.symbol, item.decision_id))
    net = [item.returns.net_return for item in completed]
    zero = Decimal(0)
    total_net = sum(net, zero)
    gross = sum((item.returns.gross_return for item in completed), zero)
    costs = sum((item.returns.simulated_cost_return for item in completed), zero)
    profit = sum((value for value in net if value > 0), zero)
    loss = sum((-value for value in net if value < 0), zero)
    wins, losses, flats = (sum(value > 0 for value in net), sum(value < 0 for value in net), sum(value == 0 for value in net))
    ordered = sorted(net)
    median = None
    if net:
        middle = len(net) // 2
        median = ordered[middle] if len(net) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    pf_state = "defined" if loss else "no_losses" if profit else "no_nonflat_outcomes" if net else "no_completed_outcomes"
    curve = [NormalizedCurvePoint(index=0, outcome_id=None, exit_time=None, cumulative_net_return=zero,
                                  normalized_value=Decimal(1), drawdown=zero)]
    cumulative, peak, max_drawdown = zero, Decimal(1), zero
    win_streak = loss_streak = best_win_streak = best_loss_streak = 0
    for index, outcome in enumerate(completed, 1):
        value = outcome.returns.net_return
        win_streak = win_streak + 1 if value > 0 else 0
        loss_streak = loss_streak + 1 if value < 0 else 0
        best_win_streak, best_loss_streak = max(best_win_streak, win_streak), max(best_loss_streak, loss_streak)
        cumulative += value
        level = 1 + cumulative
        peak = max(peak, level)
        drawdown = (peak - level) / peak
        max_drawdown = max(max_drawdown, drawdown)
        curve.append(NormalizedCurvePoint(index=index, outcome_id=outcome.outcome_id, exit_time=outcome.exit_time,
            cumulative_net_return=cumulative, normalized_value=level, drawdown=drawdown))
    decisions = [item.decision for item in observations]
    eligible = sum(item.outcome == DecisionOutcome.ELIGIBLE for item in decisions)
    return BacktestMetrics(evaluated_decision_count=len(decisions), eligible_count=eligible,
        blocked_count=sum(item.outcome == DecisionOutcome.BLOCKED for item in decisions),
        no_action_count=sum(item.outcome == DecisionOutcome.NO_ACTION for item in decisions),
        completed_count=len(completed), incomplete_count=eligible - len(completed), boundary_censored_count=len(censored),
        long_count=sum(item.direction == StrategyDirection.LONG and item.outcome == DecisionOutcome.ELIGIBLE for item in decisions),
        short_count=sum(item.direction == StrategyDirection.SHORT and item.outcome == DecisionOutcome.ELIGIBLE for item in decisions),
        win_count=wins, loss_count=losses, flat_count=flats, win_rate=Decimal(wins) / (wins + losses) if wins + losses else None,
        mean_gross_return=gross / len(completed) if completed else None,
        mean_net_return=total_net / len(completed) if completed else None, median_net_return=median,
        sum_gross_returns=gross, sum_simulated_costs=costs, sum_net_returns=total_net,
        gross_profit=profit, gross_loss=loss, profit_factor=profit / loss if loss else None, profit_factor_state=pf_state,
        best_net_return=max(net) if net else None, worst_net_return=min(net) if net else None,
        max_consecutive_wins=best_win_streak, max_consecutive_losses=best_loss_streak,
        normalized_curve=tuple(curve), normalized_max_drawdown=max_drawdown)


def cohort_metrics(observations: tuple[HistoricalDecision, ...], outcomes: tuple[BacktestSignalOutcome, ...],
                   dimension: str, *, symbols: tuple[str, ...] = ()) -> tuple[BacktestCohortMetrics, ...]:
    observations, outcomes = _validated(observations, outcomes)
    if dimension == "symbol":
        keys = sorted(set(symbols) | {item.decision.symbol for item in observations})
        key_for = lambda item: item.decision.symbol
    elif dimension == "direction":
        keys = [item.value for item in StrategyDirection]
        key_for = lambda item: item.decision.direction.value
    elif dimension == "decision_outcome":
        keys = [item.value for item in DecisionOutcome]
        key_for = lambda item: item.decision.outcome.value
    elif dimension == "coverage":
        keys = ["not_marked_incomplete", "incomplete"]
        key_for = lambda item: "incomplete" if item.decision.incomplete_strategy_coverage else "not_marked_incomplete"
    else:
        raise ValueError("unknown cohort dimension")
    result = []
    for key in keys:
        selected = tuple(item for item in observations if key_for(item) == key)
        ids = {item.decision.decision_id for item in selected}
        result.append(BacktestCohortMetrics(key=key,
            metrics=calculate_metrics(selected, (item for item in outcomes if item.decision_id in ids))))
    return tuple(result)


def chronological_segments(observations: tuple[HistoricalDecision, ...], outcomes: tuple[BacktestSignalOutcome, ...],
                           *, start: datetime, end: datetime, count: int) -> tuple[BacktestTimeSegment, ...]:
    """Equal elapsed-time segments; decision-owned cohorts, locally censored horizons.

    Decision membership is [start,end), except the final segment includes end.
    Exit at the segment end is available as of that boundary and can be scored.
    Parameters remain identical in every segment; no fitting occurs.
    """
    observations, outcomes = _validated(observations, outcomes)
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("segment count must be an integer from 1 to 100")
    if any(time.tzinfo is None or time.utcoffset() is None for time in (start, end)) or start >= end:
        raise ValueError("segment bounds must be ordered aware times")
    if any(not start <= item.decision.generated_at <= end for item in observations):
        raise ValueError("decisions fall outside the reporting range")
    delta = end - start
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if micros < count:
        raise ValueError("segment duration is below datetime resolution")
    boundaries = [start + timedelta(microseconds=micros * index // count) for index in range(count + 1)]
    result = []
    for index in range(count):
        left, right = boundaries[index:index+2]
        final = index == count - 1
        selected = tuple(item for item in observations if left <= item.decision.generated_at
                         and (item.decision.generated_at < right or final and item.decision.generated_at == right))
        ids = {item.decision.decision_id for item in selected}
        result.append(BacktestTimeSegment(index=index, start=left, end=right, includes_end=final,
            metrics=calculate_metrics(selected, (item for item in outcomes if item.decision_id in ids), cutoff=right)))
    return tuple(result)
