"""Reprice fixed raw outcomes with Phase 6 math; never rerun analytical engines."""

from datetime import datetime
from decimal import Decimal

from src.application.backtest_identity import settings_identity
from src.application.backtest_math import arithmetic, outcome_returns
from src.application.validation_metrics import validation_metrics
from src.application.backtest_settings import BacktestSettings
from src.domain.backtesting import BacktestSignalOutcome, HistoricalDecision
from src.domain.validation_costs import CostScenario, CostScenarioResult
from src.domain.validation_regimes import RegimeDefinition
from src.strategies.identity import identity


def cost_scenario_id(scenario: CostScenario) -> str:
    return identity("cost_scenario", CostScenario.model_validate(scenario))


def fixed_cost_scenarios(settings: BacktestSettings) -> tuple[CostScenario, ...]:
    """At most four unique points, ordered by assumptions (never performance).

    Bps are per side. The supplied baseline is retained; 0/0, 10/5 and 20/10
    are fixed disclosed stress assumptions. Both inputs are bounded to 100 bps.
    """
    baseline = CostScenario(fee_bps_per_side=settings.fee_bps_per_side,
                            slippage_bps_per_side=settings.slippage_bps_per_side)
    points = {(baseline.fee_bps_per_side, baseline.slippage_bps_per_side),
              (Decimal(0), Decimal(0)), (Decimal(10), Decimal(5)), (Decimal(20), Decimal(10))}
    return tuple(CostScenario(fee_bps_per_side=fee, slippage_bps_per_side=slip) for fee, slip in sorted(points))


def recost_outcomes(outcomes: tuple[BacktestSignalOutcome, ...], baseline: BacktestSettings,
                    scenario: CostScenario) -> tuple[BacktestSignalOutcome, ...]:
    baseline = BacktestSettings.model_validate(baseline)
    scenario = CostScenario.model_validate(scenario)
    scenario_settings = BacktestSettings.model_validate(baseline.model_dump() | dict(
        fee_bps_per_side=scenario.fee_bps_per_side, slippage_bps_per_side=scenario.slippage_bps_per_side))
    baseline_id = settings_identity(baseline)
    scenario_settings_id = settings_identity(scenario_settings)
    result = []
    for outcome in outcomes:
        outcome = BacktestSignalOutcome.model_validate(outcome)
        if outcome.backtest_settings_id != baseline_id or outcome.holding_period_bars != baseline.holding_period_bars:
            raise ValueError("cost sensitivity requires the original fixed baseline settings")
        if outcome.returns is not None and outcome.returns != outcome_returns(
                outcome.entry_price_raw, outcome.exit_price_raw, outcome.direction, baseline):
            raise ValueError("baseline returns do not reconcile with raw evidence")
        if scenario_settings_id == baseline_id:
            result.append(outcome)
            continue
        returns = (outcome_returns(outcome.entry_price_raw, outcome.exit_price_raw, outcome.direction, scenario_settings)
                   if outcome.returns is not None else None)
        result.append(BacktestSignalOutcome.model_validate(outcome.model_dump() | dict(
            outcome_id=identity("cost_outcome", (outcome.outcome_id, cost_scenario_id(scenario))),
            backtest_settings_id=scenario_settings_id, returns=returns)))
    return tuple(result)


@arithmetic
def analyze_costs(observations: tuple[HistoricalDecision, ...], outcomes: tuple[BacktestSignalOutcome, ...],
                  baseline: BacktestSettings, *, cutoff: datetime | None = None,
                  cutoffs: dict[str, datetime] | None = None) -> tuple[CostScenarioResult, ...]:
    baseline = BacktestSettings.model_validate(baseline)
    validation_metrics(observations, outcomes, cutoff=cutoff, cutoffs=cutoffs)
    original = {item.decision_id: item for item in outcomes}
    results = []
    for scenario in fixed_cost_scenarios(baseline):
        recosted = recost_outcomes(outcomes, baseline, scenario)
        metrics = validation_metrics(observations, recosted, cutoff=cutoff, cutoffs=cutoffs)
        # Only uncensored completed outcomes contribute to metric conclusions.
        included = {point.outcome_id for point in metrics.normalized_curve[1:]}
        changed = tuple(sorted(item.decision_id for item in recosted if item.outcome_id in included and
            (item.returns.net_return.compare(0) != original[item.decision_id].returns.net_return.compare(0))))
        warnings = []
        if metrics.completed_count < RegimeDefinition().minimum_completed_samples:
            warnings.append("SMALL_SAMPLE")
        if not metrics.completed_count:
            warnings.append("NO_COMPLETED_OUTCOMES")
        if metrics.incomplete_count:
            warnings.append("INCOMPLETE_OUTCOMES")
        if changed:
            warnings.append("NET_SIGN_CHANGED_FROM_BASELINE")
        results.append(CostScenarioResult(scenario_id=cost_scenario_id(scenario), assumptions=scenario,
            is_baseline=(scenario.fee_bps_per_side == baseline.fee_bps_per_side and
                         scenario.slippage_bps_per_side == baseline.slippage_bps_per_side),
            metrics=metrics, mean_cost_return=(metrics.sum_simulated_costs / metrics.completed_count
                                             if metrics.completed_count else None),
            sign_changed_decision_ids=changed, warnings=tuple(warnings)))
    return tuple(results)
