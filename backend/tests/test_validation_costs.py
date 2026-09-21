from decimal import Decimal, localcontext

import pytest

from backtest_fixtures import bar, historical_decision
from test_backtest_evaluator import evaluator, start
from test_walk_forward_evaluator import dataset, protocol
from src.application.backtest_metrics import calculate_metrics
from src.application.backtest_settings import BacktestSettings
from src.application.validation_costs import analyze_costs, cost_scenario_id, fixed_cost_scenarios, recost_outcomes
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.validation_costs import CostScenario


def captured(direction="LONG", exit="100.1"):
    engine = evaluator(horizon=1)
    decision = start(engine, direction=direction)
    outcome, = engine.advance(bar(1, opened="100", closed=exit))
    pending = historical_decision(bar(1), direction=direction)
    engine.accept(pending)
    incomplete, = engine.finish()
    diagnostic = historical_decision(bar(2), outcome="NO_ACTION")
    return (decision, pending, diagnostic), (outcome, incomplete), BacktestSettings(holding_period_bars=1)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("exit", ["1", "50", "99.9", "100", "100.1", "150", "1000"])
def test_zero_baseline_and_monotone_costs_preserve_raw_outcomes(direction, exit):
    observations, outcomes, baseline = captured(direction, exit)
    original = tuple(item.model_dump_json() for item in outcomes)
    previous_net = None
    for scenario in fixed_cost_scenarios(baseline):
        adjusted = recost_outcomes(outcomes, baseline, scenario)
        for left, right in zip(outcomes, adjusted):
            assert left.model_dump(exclude={"returns", "outcome_id", "backtest_settings_id"}) == right.model_dump(
                exclude={"returns", "outcome_id", "backtest_settings_id"})
        assert adjusted[1].returns is None and adjusted[1].status == "INCOMPLETE"
        net = adjusted[0].returns.net_return
        assert previous_net is None or net <= previous_net
        previous_net = net
        if scenario.fee_bps_per_side == scenario.slippage_bps_per_side == 0:
            assert net == outcomes[0].returns.gross_return
        if scenario.fee_bps_per_side == 5:
            assert adjusted == outcomes
    assert original == tuple(item.model_dump_json() for item in outcomes)
    results = analyze_costs(observations, outcomes, baseline)
    assert len(results) == 4 and sum(item.is_baseline for item in results) == 1
    assert all(item.metrics.eligible_count == 2 and item.metrics.incomplete_count == 1 for item in results)
    assert all(item.metrics.sum_gross_returns == results[0].metrics.sum_gross_returns for item in results)
    assert next(item for item in results if item.is_baseline).metrics == calculate_metrics(observations, outcomes)


def test_sign_change_is_disclosed_without_ranking_or_probability():
    observations, outcomes, baseline = captured()
    results = analyze_costs(observations, outcomes, baseline)
    assert results[0].sign_changed_decision_ids == (outcomes[0].decision_id,)
    assert "NET_SIGN_CHANGED_FROM_BASELINE" in results[0].warnings
    assert all("SMALL_SAMPLE" in item.warnings for item in results)
    assert results == analyze_costs(tuple(reversed(observations)), tuple(reversed(outcomes)), baseline)
    with localcontext() as context:
        context.prec = 4
        assert results == analyze_costs(observations, outcomes, baseline)


@pytest.mark.parametrize("field", ["fee_bps_per_side", "slippage_bps_per_side"])
@pytest.mark.parametrize("value", ["-1", "100.001", "NaN", "Infinity"])
def test_cost_domain_bounded_and_finite(field, value):
    with pytest.raises(ValueError):
        CostScenario(**(dict(fee_bps_per_side=0, slippage_bps_per_side=0) | {field: value}))


@pytest.mark.parametrize("fee,slip,expected", [(0, 0, 3), (10, 5, 3), (20, 10, 3), (7, 3, 4)])
def test_grid_deduplicates_baseline_and_has_canonical_id(fee, slip, expected):
    points = fixed_cost_scenarios(BacktestSettings(fee_bps_per_side=fee, slippage_bps_per_side=slip))
    assert len(points) == expected
    for point in points:
        assert len(cost_scenario_id(point).removeprefix("cost_scenario_")) == 64
        assert cost_scenario_id(point) == cost_scenario_id(CostScenario.model_validate_json(point.model_dump_json()))


def test_empty_no_signals_and_invalid_baseline():
    baseline = BacktestSettings()
    for result in analyze_costs((), (), baseline):
        assert result.metrics.completed_count == 0 and result.mean_cost_return is None
        assert "NO_COMPLETED_OUTCOMES" in result.warnings
    observations, outcomes, baseline = captured()
    with pytest.raises(ValueError, match="original fixed baseline"):
        analyze_costs(observations, outcomes, BacktestSettings(holding_period_bars=2))
    with pytest.raises(ValueError):
        analyze_costs(observations, outcomes, baseline.model_copy(update={"fee_bps_per_side": Decimal(101)}))


@pytest.mark.asyncio
async def test_sensitivity_uses_fixed_production_evidence_without_replay(monkeypatch):
    data = dataset(count=80)
    evaluator = WalkForwardEvaluator(protocol(data, test_boundaries=30, step_boundaries=30))
    evaluated = await evaluator.run(data)
    before = evaluated.model_dump_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("cost analysis must never rerun analytical decisions")

    monkeypatch.setattr(type(evaluator.replay), "frames", forbidden)
    window = evaluated.windows[0]
    costs = analyze_costs(window.decisions, window.outcomes, evaluator.backtest_settings, cutoff=window.split.test_end)
    assert next(item for item in costs if item.is_baseline).metrics == window.metrics
    assert evaluated.model_dump_json() == before
