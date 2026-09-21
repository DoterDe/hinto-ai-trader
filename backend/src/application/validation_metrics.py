"""Preserve each decision's originating window cutoff when pooling disjoint tests."""

from datetime import datetime

from src.application.backtest_metrics import calculate_metrics, expected_exit_time
from src.domain.backtesting import BacktestMetrics


def validation_metrics(observations, outcomes, *, cutoff: datetime | None = None,
                       cutoffs: dict[str, datetime] | None = None) -> BacktestMetrics:
    observations, outcomes = tuple(observations), tuple(outcomes)
    if cutoff is not None and cutoffs is not None:
        raise ValueError("use a single cutoff or originating-window cutoffs")
    result = calculate_metrics(observations, outcomes, cutoff=cutoff)
    if cutoffs is None:
        return result
    censored = 0
    for item in observations:
        if item.decision.decision_id not in cutoffs or cutoffs[item.decision.decision_id] < item.source_bar_close_time:
            raise ValueError("originating window cutoff is missing or precedes decision")
    for item in outcomes:
        if expected_exit_time(item) > cutoffs[item.decision_id]:
            if item.status == "COMPLETED":
                raise ValueError("pooled evidence cannot borrow a post-window exit")
            censored += 1
    return BacktestMetrics.model_validate(result.model_dump() | {"boundary_censored_count": censored})
