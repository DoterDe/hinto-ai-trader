"""Offline replay, independent signal evaluation, and deterministic reporting."""

from collections.abc import Iterable, Sequence
from contextlib import aclosing

from src.application.backtest_evaluator import BacktestEvaluator
from src.application.backtest_identity import BACKTEST_ENGINE_VERSION, DatasetIdentity, settings_identity
from src.application.backtest_metrics import calculate_metrics, chronological_segments, cohort_metrics
from src.application.backtest_settings import BacktestSettings
from src.application.decision_identity import DECISION_ENGINE_VERSION, policy_identity
from src.application.decision_settings import DecisionSettings
from src.application.feature_settings import FeatureSettings
from src.application.historical_replay import HistoricalReplay
from src.application.strategy_engine import ENGINE_VERSION as STRATEGY_ENGINE_VERSION
from src.application.strategy_settings import StrategySettings
from src.domain.backtesting import BacktestRunMetadata, BacktestRunReport
from src.domain.market_data import KlineEvent
from src.strategies.identity import identity

LIMITATIONS = (
    "signal_level_overlapping_horizons_not_portfolio_returns",
    "bar_end_availability_and_next_open_entry_assumed_without_latency",
    "book_trade_mark_and_funding_observations_not_supplied",
    "cost_assumptions_not_verified_exchange_fees_or_fill_quality",
    "no_funding_liquidation_margin_market_impact_taxes_or_capital_constraints",
    "bounded_feature_history_reseeds_after_eviction_or_gaps",
    "additive_normalized_curve_can_be_negative_drawdown_can_exceed_one",
    "segment_boundary_horizons_censored_without_parameter_fitting",
    "numeric_regime_context_only_no_invented_regime_labels",
    "finite_run_decisions_outcomes_and_dedupe_retained_in_memory",
    "historical_results_do_not_predict_future_returns",
)


class BacktestEngine:
    def __init__(self, *, symbols: Sequence[str], interval: str = "1m",
                 settings: BacktestSettings | None = None,
                 feature_settings: FeatureSettings | None = None,
                 strategy_settings: StrategySettings | None = None,
                 decision_settings: DecisionSettings | None = None) -> None:
        self.settings = BacktestSettings.model_validate(settings) if settings is not None else BacktestSettings()
        self.replay = HistoricalReplay(symbols=symbols, interval=interval, feature_settings=feature_settings,
            strategy_settings=strategy_settings, decision_settings=decision_settings)

    async def run(self, bars: Iterable[KlineEvent]) -> BacktestRunReport:
        """Consume a finite iterator once; each run owns and cleans up its state.

        Only transient frames contain feature/strategy snapshots and raw bars.
        The final report retains compact decisions/regime context and outcomes.
        """
        evaluator = BacktestEvaluator(symbols=self.replay.symbols, interval=self.replay.interval, settings=self.settings)
        dataset = DatasetIdentity()
        observations, outcomes = [], []
        started = ended = None
        async with aclosing(self.replay.frames(bars)) as frames:
            async for frame in frames:
                dataset.add(frame.bar)
                if started is None:
                    started = frame.bar.open_time
                ended = frame.bar.close_time
                outcomes.extend(evaluator.advance(frame.bar))
                if evaluator.accept(frame.observation):
                    observations.append(frame.observation)
        outcomes.extend(evaluator.finish())
        decisions = tuple(observations)
        results = tuple(sorted(outcomes, key=lambda item: (item.decision_time, item.symbol, item.decision_id)))
        feature_id = identity("feature_settings", self.replay.feature_settings)
        strategy_id = identity("settings", self.replay.strategy_settings)
        policy_id = policy_identity(self.replay.decision_settings, self.replay.symbols)
        backtest_id = settings_identity(self.settings)
        run_id = identity("backtest_run", (BACKTEST_ENGINE_VERSION, STRATEGY_ENGINE_VERSION,
            DECISION_ENGINE_VERSION, dataset.value, feature_id, strategy_id, policy_id,
            backtest_id, self.replay.symbols, self.replay.interval))
        metadata = BacktestRunMetadata(run_id=run_id, dataset_id=dataset.value,
            engine_version=BACKTEST_ENGINE_VERSION, started_from=started, ended_at=ended,
            symbols=self.replay.symbols, interval=self.replay.interval, input_count=dataset.count,
            duplicate_decision_reads=evaluator.duplicate_reads, feature_settings_id=feature_id,
            strategy_settings_id=strategy_id, decision_policy_id=policy_id, backtest_settings_id=backtest_id)
        return BacktestRunReport(metadata=metadata, decisions=decisions, outcomes=results,
            metrics=calculate_metrics(decisions, results),
            per_symbol=cohort_metrics(decisions, results, "symbol", symbols=self.replay.symbols),
            per_direction=cohort_metrics(decisions, results, "direction"),
            per_decision_outcome=cohort_metrics(decisions, results, "decision_outcome"),
            per_strategy_coverage=cohort_metrics(decisions, results, "coverage"),
            chronological_segments=chronological_segments(decisions, results, start=started, end=ended,
                count=self.settings.chronological_segments) if started is not None else (), limitations=LIMITATIONS)
