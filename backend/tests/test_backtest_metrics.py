from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from backtest_fixtures import START, bar, historical_decision
from src.application.backtest_metrics import calculate_metrics, chronological_segments, cohort_metrics
from src.domain.backtesting import BacktestSignalOutcome, OutcomeReturns


def sample(index, net, *, cost="0", symbol="BTCUSDT", direction="LONG", horizon=1, status="COMPLETED"):
    observation = historical_decision(bar(index, symbol=symbol), direction=direction)
    net, cost = Decimal(net), Decimal(cost)
    gross = net + cost
    raw_exit = Decimal(100) * (1 + gross * (1 if direction == "LONG" else -1))
    completed = status == "COMPLETED"
    outcome = BacktestSignalOutcome(outcome_id=f"outcome_{symbol}_{index}",
        decision_id=observation.decision.decision_id, observation_id=observation.decision.observation_id,
        symbol=symbol, interval="1m", direction=direction, decision_time=observation.decision.generated_at,
        source_bar_open_time=observation.source_bar_open_time, holding_period_bars=horizon,
        backtest_settings_id="backtest_test", entry_time=observation.decision.generated_at,
        entry_price_raw=100, exit_time=START + timedelta(minutes=index + horizon + 1) if completed else None,
        exit_price_raw=raw_exit if completed else None,
        returns=OutcomeReturns(effective_entry_price=100, effective_exit_price=raw_exit,
            gross_return=gross, slippage_cost_return=0, fee_cost_return=cost,
            simulated_cost_return=cost, net_return=net) if completed else None,
        favorable_excursion=max(Decimal(0), gross) if completed else None,
        adverse_excursion=min(Decimal(0), gross) if completed else None,
        status=status, reason="horizon_completed" if completed else "dataset_ended")
    return observation, outcome


def metrics(values):
    pairs = [sample(index, value) for index, value in enumerate(values)]
    return calculate_metrics([item[0] for item in pairs], [item[1] for item in pairs])


def test_empty_metrics_are_explicit_without_nan_or_infinity():
    result = metrics([])
    assert result.evaluated_decision_count == result.completed_count == 0
    assert result.win_rate is result.mean_net_return is result.median_net_return is None
    assert result.best_net_return is result.worst_net_return is result.profit_factor is None
    assert result.profit_factor_state == "no_completed_outcomes"
    assert result.sum_gross_returns == result.sum_simulated_costs == result.sum_net_returns == 0
    assert len(result.normalized_curve) == 1 and result.normalized_curve[0].normalized_value == 1
    assert result.normalized_max_drawdown == 0
    assert "NaN" not in result.model_dump_json() and "Infinity" not in result.model_dump_json()


@pytest.mark.parametrize("values,wins,losses,flats,rate,pf,pf_state,mean,median", [
    ([".1"], 1, 0, 0, "1", None, "no_losses", ".1", ".1"),
    (["-.1"], 0, 1, 0, "0", "0", "defined", "-.1", "-.1"),
    ([".1", ".3"], 2, 0, 0, "1", None, "no_losses", ".2", ".2"),
    (["-.1", "-.3"], 0, 2, 0, "0", "0", "defined", "-.2", "-.2"),
    (["0", "0"], 0, 0, 2, None, None, "no_nonflat_outcomes", "0", "0"),
    ([".3", "-.1", "0"], 1, 1, 1, ".5", "3", "defined", None, "0"),
])
def test_independent_win_loss_flat_and_profit_factor_cases(values, wins, losses, flats, rate, pf, pf_state, mean, median):
    result = metrics(values)
    assert (result.win_count, result.loss_count, result.flat_count) == (wins, losses, flats)
    assert result.win_rate == (Decimal(rate) if rate is not None else None)
    assert result.profit_factor == (Decimal(pf) if pf is not None else None)
    assert result.profit_factor_state == pf_state
    if mean is not None:
        assert result.mean_net_return == Decimal(mean)
    assert result.median_net_return == Decimal(median)


def test_costs_expectancy_profit_and_loss_have_distinct_meanings():
    pairs = [sample(0, ".20", cost=".01"), sample(1, "-.05", cost=".02"), sample(2, "0", cost=".03")]
    result = calculate_metrics([pair[0] for pair in pairs], [pair[1] for pair in pairs])
    assert result.sum_gross_returns == Decimal(".21")
    assert result.sum_simulated_costs == Decimal(".06")
    assert result.sum_net_returns == Decimal(".15")
    assert result.mean_gross_return == Decimal(".07") and result.mean_net_return == Decimal(".05")
    assert result.gross_profit == Decimal(".20") and result.gross_loss == Decimal(".05")
    assert result.profit_factor == 4 and result.win_rate == Decimal(".5")
    assert result.best_net_return == Decimal(".20") and result.worst_net_return == Decimal("-.05")


def test_curve_drawdown_streaks_and_flats_are_independently_calculated():
    result = metrics([".25", "-.25", "-.125", ".25", "0", ".125"])
    assert [point.normalized_value for point in result.normalized_curve] == list(map(Decimal,
        ["1", "1.25", "1", ".875", "1.125", "1.125", "1.25"]))
    assert [point.drawdown for point in result.normalized_curve] == list(map(Decimal,
        ["0", "0", ".2", ".3", ".1", ".1", "0"]))
    assert result.normalized_max_drawdown == Decimal(".3")
    assert result.max_consecutive_wins == 1 and result.max_consecutive_losses == 2
    assert result.gross_profit == Decimal(".625") and result.gross_loss == Decimal(".375")
    assert result.win_rate == Decimal(".6") and result.median_net_return == Decimal(".0625")


def test_additive_curve_can_cross_zero_without_clamping_or_account_claims():
    observation, outcome = sample(0, "-1.5", direction="SHORT")
    result = calculate_metrics((observation,), (outcome,))
    assert result.normalized_curve[-1].normalized_value == Decimal("-.5")
    assert result.normalized_max_drawdown == Decimal("1.5")


def test_metrics_sort_by_exit_time_and_not_container_order():
    pairs = [sample(0, ".25", horizon=5), sample(1, "-.25"), sample(2, "-.125")]
    ordered = calculate_metrics([p[0] for p in pairs], [p[1] for p in pairs])
    reversed_result = calculate_metrics([p[0] for p in reversed(pairs)], [p[1] for p in reversed(pairs)])
    assert ordered == reversed_result
    assert [point.outcome_id for point in ordered.normalized_curve[1:]] == [pairs[1][1].outcome_id, pairs[2][1].outcome_id, pairs[0][1].outcome_id]
    assert ordered.max_consecutive_losses == 2


def test_diagnostic_counts_and_incomplete_outcomes_reconcile():
    ready, completed = sample(0, ".1")
    pending, incomplete = sample(1, "0", direction="SHORT", status="INCOMPLETE")
    blocked = historical_decision(bar(2), outcome="BLOCKED")
    neutral = historical_decision(bar(3), outcome="NO_ACTION")
    result = calculate_metrics((ready, pending, blocked, neutral), (completed, incomplete))
    assert result.evaluated_decision_count == 4
    assert (result.eligible_count, result.blocked_count, result.no_action_count) == (2, 1, 1)
    assert (result.completed_count, result.incomplete_count, result.long_count, result.short_count) == (1, 1, 1, 1)
    assert result.win_count == 1 and result.mean_net_return == Decimal(".1")


def test_symbol_direction_outcome_and_coverage_cohorts_reconcile():
    btc, long = sample(0, ".1")
    eth, short = sample(1, "-.1", symbol="ETHUSDT", direction="SHORT")
    eth = eth.model_copy(update={"decision": eth.decision.model_copy(update={
        "incomplete_strategy_coverage": True,
        "reasons": eth.decision.reasons + ({"code": "incomplete_strategy_coverage"},)})})
    neutral = historical_decision(bar(2), outcome="NO_ACTION")
    observations, outcomes = (btc, eth, neutral), (long, short)
    for dimension in ("symbol", "direction", "decision_outcome", "coverage"):
        cohorts = cohort_metrics(observations, outcomes, dimension, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        assert sum(item.metrics.evaluated_decision_count for item in cohorts) == 3
        assert sum(item.metrics.completed_count for item in cohorts) == 2
    symbols = {item.key: item.metrics for item in cohort_metrics(observations, outcomes, "symbol")}
    assert symbols["BTCUSDT"].sum_net_returns == Decimal(".1")
    assert symbols["ETHUSDT"].sum_net_returns == Decimal("-.1")
    coverage = {item.key: item.metrics for item in cohort_metrics(observations, outcomes, "coverage")}
    assert coverage["incomplete"].short_count == 1
    with pytest.raises(ValueError):
        cohort_metrics(observations, outcomes, "opaque_regime")


def test_chronological_segments_censor_cross_boundary_horizons():
    first, scored = sample(0, ".1", horizon=1)  # decision 1, exit 2
    crossing, future = sample(1, ".9", horizon=3)  # decision 2, exit 5
    boundary, later = sample(2, "-.2", horizon=1)  # decision 3 belongs to second segment
    observations, outcomes = (first, crossing, boundary), (scored, future, later)
    segments = chronological_segments(observations, outcomes, start=START, end=START + timedelta(minutes=6), count=2)
    assert [item.metrics.evaluated_decision_count for item in segments] == [2, 1]
    assert segments[0].metrics.sum_net_returns == Decimal(".1")
    assert segments[0].metrics.completed_count == 1 and segments[0].metrics.incomplete_count == 1
    assert segments[0].metrics.boundary_censored_count == 1
    assert segments[1].metrics.sum_net_returns == Decimal("-.2")
    changed_future = sample(1, "-.8", horizon=3)[1]
    changed = chronological_segments(observations, (scored, changed_future, later), start=START,
                                    end=START + timedelta(minutes=6), count=2)
    assert changed[0] == segments[0]
    # Even eventual completion vs truncation cannot affect an earlier segment.
    missing_future = sample(1, "0", horizon=3, status="INCOMPLETE")[1]
    truncated = chronological_segments(observations, (scored, missing_future, later), start=START,
                                      end=START + timedelta(minutes=6), count=2)
    assert truncated[0] == segments[0]


def test_final_segment_includes_end_and_empty_segments_are_valid():
    observation, outcome = sample(3, "0", status="INCOMPLETE")
    segments = chronological_segments((observation,), (outcome,), start=START,
        end=START + timedelta(minutes=4), count=4)
    assert [item.metrics.eligible_count for item in segments] == [0, 0, 0, 1]
    assert segments[-1].includes_end and segments[-1].metrics.incomplete_count == 1


@pytest.mark.parametrize("count", [0, True, 101, 1.5])
def test_invalid_segmentation_count_fails(count):
    with pytest.raises(ValueError):
        chronological_segments((), (), start=START, end=START + timedelta(minutes=1), count=count)


def test_malformed_duplicate_missing_and_noneligible_outcomes_are_rejected():
    observation, outcome = sample(0, ".1")
    for observations, outcomes in (((observation, observation), (outcome,)), ((observation,), (outcome, outcome)),
            ((observation,), ()), ((), (outcome,)), ((historical_decision(bar(), outcome="NO_ACTION"),), (outcome,))):
        with pytest.raises(ValueError):
            calculate_metrics(observations, outcomes)
    with pytest.raises(ValueError):
        calculate_metrics((observation,), (outcome.model_copy(update={"symbol": "ETHUSDT"}),))
    with pytest.raises(ValueError):
        calculate_metrics((observation,), (outcome.model_copy(update={"returns": outcome.returns.model_copy(update={"net_return": Decimal("NaN")})}),))


def test_metrics_do_not_depend_on_ambient_decimal_context():
    expected = metrics([".25", "-.25", "-.125", ".25", "0", ".125"])
    with localcontext() as context:
        context.prec = 5
        result = metrics([".25", "-.25", "-.125", ".25", "0", ".125"])
        assert result == expected and context.prec == 5


@pytest.mark.parametrize("cutoff", [START.replace(tzinfo=None), 1577836800])
def test_metric_cutoff_must_be_an_aware_datetime(cutoff):
    with pytest.raises(ValueError, match="cutoff"):
        calculate_metrics((), (), cutoff=cutoff)
