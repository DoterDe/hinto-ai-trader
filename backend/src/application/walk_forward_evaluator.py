"""Past-only context replay and test-only outcomes using unchanged Phase 6 logic."""

import asyncio
from bisect import bisect_left
from contextlib import aclosing

from src.application.backtest_evaluator import BacktestEvaluator
from src.application.backtest_identity import BACKTEST_ENGINE_VERSION, DatasetIdentity, settings_identity
from src.application.backtest_metrics import calculate_metrics
from src.application.backtest_settings import BacktestSettings
from src.application.decision_identity import DECISION_ENGINE_VERSION, policy_identity
from src.application.decision_settings import DecisionSettings
from src.application.feature_settings import FeatureSettings
from src.application.historical_dataset import verify_historical_dataset
from src.application.historical_replay import HistoricalReplay
from src.application.strategy_engine import ENGINE_VERSION as STRATEGY_ENGINE_VERSION
from src.application.strategy_settings import StrategySettings
from src.application.walk_forward import _build_plan
from src.application.validation_regimes import assign_regime
from src.domain.historical_dataset import HistoricalDataset
from src.domain.walk_forward import (
    WalkForwardEngineIdentity, WalkForwardEvaluation, WalkForwardEvidence,
    WalkForwardProtocol, WalkForwardWindowResult,
)
from src.strategies.identity import identity


class WalkForwardEvaluator:
    """A fixed configuration for all independent splits; no state crosses windows.

    The protocol declares a contiguous past-context requirement for every symbol.
    Admitted test gaps then follow existing replay/readiness/incomplete semantics.
    No post-window exit tail is consumed. Context decisions are never scored.
    """

    def __init__(self, protocol: WalkForwardProtocol, *, feature_settings: FeatureSettings | None = None,
                 strategy_settings: StrategySettings | None = None, decision_settings: DecisionSettings | None = None,
                 backtest_settings: BacktestSettings | None = None) -> None:
        self.protocol = WalkForwardProtocol.model_validate(protocol)
        self.replay = HistoricalReplay(symbols=self.protocol.symbols, interval=self.protocol.interval,
            feature_settings=feature_settings, strategy_settings=strategy_settings, decision_settings=decision_settings)
        self.backtest_settings = BacktestSettings.model_validate(backtest_settings) if backtest_settings is not None else BacktestSettings()

    async def run(self, dataset: HistoricalDataset) -> WalkForwardEvaluation:
        dataset = verify_historical_dataset(dataset)
        # Capture a validated configuration before the first await; environment
        # changes or another caller cannot retune a later split in this run.
        protocol = WalkForwardProtocol.model_validate(self.protocol)
        replay = HistoricalReplay(symbols=protocol.symbols, interval=protocol.interval,
            feature_settings=self.replay.feature_settings, strategy_settings=self.replay.strategy_settings,
            decision_settings=self.replay.decision_settings)
        costs = BacktestSettings.model_validate(self.backtest_settings)
        plan = _build_plan(dataset, protocol, replay.feature_settings)
        engines = WalkForwardEngineIdentity(backtest_engine_version=BACKTEST_ENGINE_VERSION,
            strategy_engine_version=STRATEGY_ENGINE_VERSION, decision_engine_version=DECISION_ENGINE_VERSION,
            feature_settings_id=identity("feature_settings", replay.feature_settings),
            strategy_settings_id=identity("settings", replay.strategy_settings),
            decision_policy_id=policy_identity(replay.decision_settings, replay.symbols),
            backtest_settings_id=settings_identity(costs))
        opens = [bar.open_time for bar in dataset.bars]
        windows = []
        for split in plan.splits:
            await asyncio.sleep(0)  # permit cancellation between short/rejected windows
            lo, hi = (bisect_left(opens, time) for time in (split.context_start, split.test_end))
            rows = dataset.bars[lo:hi]
            content = DatasetIdentity()
            for bar in rows:
                content.add(bar)
            observations, outcomes, evidence = [], [], []
            warnings = list(split.warnings)
            metrics = None
            status = split.status
            if split.status == "READY":
                evaluator = BacktestEvaluator(symbols=protocol.symbols, interval=protocol.interval, settings=costs)
                async with aclosing(replay.frames(rows)) as frames:
                    async for frame in frames:
                        if frame.bar.open_time < split.test_start:
                            continue  # warm real analytical state, never accept context decisions
                        outcomes.extend(evaluator.advance(frame.bar))
                        if evaluator.accept(frame.observation):
                            observations.append(frame.observation)
                            evidence.append(WalkForwardEvidence(symbol=frame.bar.symbol, boundary=frame.bar.close_time,
                                bar_id=identity("bar", frame.bar), feature_snapshot_id=identity("features", frame.features),
                                strategy_snapshot_id=identity("strategy_snapshot", frame.strategy),
                                decision_id=frame.observation.decision.decision_id,
                                regime=assign_regime(frame.features, frame.bar.close_time)))
                outcomes.extend(evaluator.finish())
                outcomes.sort(key=lambda item: (item.decision_time, item.symbol, item.decision_id))
                metrics = calculate_metrics(observations, outcomes, cutoff=split.test_end)
                if metrics.eligible_count == 0:
                    warnings.append("VALID_NO_SIGNALS")
                if metrics.incomplete_count:
                    warnings.append("INCOMPLETE_OUTCOMES")
                if metrics.boundary_censored_count:
                    warnings.append("BOUNDARY_CENSORED_OUTCOMES")
                status = "EVALUATED"
            payload = dict(engines=engines, input_content_id=content.value, status=status,
                           decisions=tuple(observations), outcomes=tuple(outcomes), evidence=tuple(evidence),
                           metrics=metrics, warnings=tuple(warnings))
            # Global provenance is retained on split.dataset_id, but unrelated
            # future content cannot change a completed window's local identity.
            result_id = identity("walk_window", dict(split=split.model_dump(exclude={"dataset_id"}), **payload))
            windows.append(WalkForwardWindowResult(result_id=result_id, split=split, **payload))
        evaluation_id = identity("walk_evaluation", (protocol.dataset_id, plan.protocol_id, engines,
                                                     plan.status, tuple(window.result_id for window in windows)))
        return WalkForwardEvaluation(evaluation_id=evaluation_id, protocol=protocol, plan=plan,
                                     engines=engines, windows=tuple(windows))
