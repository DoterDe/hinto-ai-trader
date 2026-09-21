from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from backtest_fixtures import bar
from strategy_fixtures import features, state
from test_backtest_metrics import sample
from test_walk_forward_evaluator import dataset, protocol
from src.application.validation_regimes import analyze_regimes, assign_regime
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.features import Readiness
from src.domain.validation_regimes import RegimeDefinition


def snapshot(boundary=None, **updates):
    value = features(**updates)
    boundary = boundary or value.generated_at
    return value.model_copy(update={"generated_at": boundary, "closed_candle_time": boundary})


@pytest.mark.parametrize("separation,efficiency,expected", [
    (".001", ".25", "UPTREND"), ("-.001", ".25", "DOWNTREND"),
    (".0005", "1", "RANGE"), ("-.0005", "1", "RANGE"),
    (".1", ".2499", "RANGE"), ("0", "1", "RANGE"),
])
@pytest.mark.parametrize("atr,expected_vol", [("0", "LOW"), (".005", "LOW"),
    (".005001", "MEDIUM"), (".02", "MEDIUM"), (".020001", "HIGH")])
def test_fixed_thresholds(separation, efficiency, expected, atr, expected_vol):
    value = snapshot(regime=dict(normalized_ema_separation=separation, directional_efficiency=efficiency),
                     volatility=dict(normalized_atr=atr))
    assigned = assign_regime(value, value.generated_at)
    assert (assigned.trend, assigned.volatility) == (expected, expected_vol)
    assert assigned.unknown_reasons == ()
    assert assigned.normalized_atr == Decimal(atr)
    assert len(assigned.assignment_id.removeprefix("regime_assignment_")) == 64


@pytest.mark.parametrize("group", ["regime", "volatility"])
@pytest.mark.parametrize("readiness", [Readiness.STALE, Readiness.UNAVAILABLE, Readiness.WARMING_UP])
def test_unknown_dependencies_are_independent(group, readiness):
    value = state(snapshot(), group, readiness)
    assigned = assign_regime(value, value.generated_at)
    assert (assigned.trend == "UNKNOWN") == (group == "regime")
    assert (assigned.volatility == "UNKNOWN") == (group == "volatility")
    assert len(assigned.unknown_reasons) == 1


def test_boundary_mismatch_does_not_use_future_or_older_snapshot():
    value = snapshot()
    for delta in (-1, 1):
        assigned = assign_regime(value, value.generated_at + timedelta(minutes=delta))
        assert assigned.trend == assigned.volatility == "UNKNOWN"
        assert assigned.unknown_reasons == ("EVIDENCE_BOUNDARY_MISMATCH",)


def test_empty_and_sparse_groups_retain_counts_and_null_statistics():
    empty = analyze_regimes((), (), (), symbols=("ETHUSDT", "BTCUSDT"))
    assert len(empty.groups) == 10
    assert [g.key for g in empty.groups[:2]] == ["BTCUSDT", "ETHUSDT"]
    assert all(g.warnings == ("EMPTY_GROUP", "SMALL_SAMPLE") for g in empty.groups)
    assert all(g.confidence.count == 0 and g.confidence.mean is None and g.metrics.win_rate is None for g in empty.groups)
    observations, outcomes, assignments = [], [], []
    for index, net in enumerate((".1", "-.1", "0")):
        observation, outcome = sample(index, net)
        observations.append(observation)
        outcomes.append(outcome)
        assignments.append(assign_regime(snapshot(observation.source_bar_close_time), observation.source_bar_close_time))
    result = analyze_regimes(tuple(observations), tuple(outcomes), tuple(assignments), symbols=("BTCUSDT",))
    group = result.groups[0]
    assert group.metrics.completed_count == 3 and group.metrics.win_rate == Decimal(".5")
    assert group.confidence.count == 3 and group.confidence.mean == Decimal(".8")
    assert group.composite_score.mean == 80
    assert group.warnings == ("SMALL_SAMPLE",)
    assert "NaN" not in result.model_dump_json() and "Infinity" not in result.model_dump_json()
    reversed_result = analyze_regimes(tuple(reversed(observations)), tuple(reversed(outcomes)),
        tuple(reversed(assignments)), symbols=("BTCUSDT",))
    assert result == reversed_result
    with localcontext() as context:
        context.prec = 4
        assert result == analyze_regimes(tuple(observations), tuple(outcomes), tuple(assignments), symbols=("BTCUSDT",))


@pytest.mark.parametrize("count,sparse", [(29, True), (30, False)])
def test_sample_threshold_counts_completed_outcomes(count, sparse):
    pairs = [sample(index, ".1") for index in range(count)]
    observations = tuple(pair[0] for pair in pairs)
    assignments = tuple(assign_regime(snapshot(item.source_bar_close_time), item.source_bar_close_time) for item in observations)
    result = analyze_regimes(observations, tuple(pair[1] for pair in pairs), assignments, symbols=("BTCUSDT",))
    assert ("SMALL_SAMPLE" in result.groups[0].warnings) == sparse


def test_incomplete_outcomes_and_malformed_evidence_are_explicit():
    observation, outcome = sample(0, "0", status="INCOMPLETE")
    assigned = assign_regime(snapshot(observation.source_bar_close_time), observation.source_bar_close_time)
    result = analyze_regimes((observation,), (outcome,), (assigned,), symbols=("BTCUSDT",))
    assert result.groups[0].metrics.incomplete_count == 1
    assert "INCOMPLETE_OUTCOMES" in result.groups[0].warnings
    for assignments in ((), (assigned, assigned), (assigned.model_copy(update={"trend": "UPTREND"}),)):
        with pytest.raises(ValueError):
            analyze_regimes((observation,), (outcome,), assignments, symbols=("BTCUSDT",))


def test_assignments_are_immutable_and_thresholds_not_tunable():
    value = snapshot()
    assigned = assign_regime(value, value.generated_at)
    with pytest.raises(ValueError):
        assigned.trend = "UPTREND"
    with pytest.raises(ValueError):
        RegimeDefinition(normalized_atr_low_upper=Decimal(".1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["price", "volatility"])
async def test_future_changes_preserve_earlier_assignments_and_originating_decision(mutation):
    data = dataset(count=85)
    selected = protocol(data, test_boundaries=35, step_boundaries=35)
    first = await WalkForwardEvaluator(selected).run(data)
    outcome = next(item for item in first.windows[0].outcomes if item.status == "COMPLETED")
    entry = next(index for index, row in enumerate(data.bars) if row.open_time == outcome.entry_time)
    row = data.bars[entry]
    replacement = (bar(entry, opened="900", closed="901") if mutation == "price" else
                   row.model_copy(update={"high": row.high * 2}))
    changed = dataset(data.bars[:entry] + (replacement,) + data.bars[entry + 1:])
    second = await WalkForwardEvaluator(selected.model_copy(update={"dataset_id": changed.manifest.dataset_id})).run(changed)
    before = [item for item in first.windows[0].evidence if item.boundary <= outcome.entry_time]
    after = [item for item in second.windows[0].evidence if item.boundary <= outcome.entry_time]
    assert before == after and before
    later = next(item for item in second.windows[0].outcomes if item.decision_id == outcome.decision_id)
    assert later != outcome  # labels at decision time survive altered eventual evidence
