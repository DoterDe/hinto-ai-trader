"""On-demand, exchange-independent analytical evaluation; no tasks or orders."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from src.application.strategy_settings import StrategySettings
from src.domain.features import FeatureSnapshot
from src.domain.strategies import (
    StrategyAssessment, StrategyCandidate, StrategyDirection, StrategyEngineStatus,
    StrategyId, StrategyReadiness, StrategySnapshot, StrategySymbolStatus,
)
from src.strategies.base import Strategy, unavailable_state
from src.strategies.identity import identity, observation_identity, snapshot_identity
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import MomentumContinuation
from src.strategies.scoring import arithmetic, sign
from src.strategies.trend_following import TrendFollowing

ENGINE_VERSION = "strategy-engine-v1"


class FeatureProvider(Protocol):
    def latest(self, symbol: str) -> FeatureSnapshot: ...


@dataclass(frozen=True)
class Consensus:
    readiness: StrategyReadiness
    score: Decimal | None
    confidence: Decimal | None
    agreement: Decimal | None
    direction: StrategyDirection
    contributors: tuple[StrategyId, ...]
    reasons: tuple[str, ...]


@arithmetic
def aggregate(assessments: tuple[StrategyAssessment, ...], settings: StrategySettings) -> Consensus:
    """Weighted mean score; configured coverage and disagreement reduce confidence."""
    settings = StrategySettings.model_validate(settings)
    assessments = tuple(StrategyAssessment.model_validate(item) for item in assessments)
    by_id = {item.strategy_id: item for item in assessments}
    if len(by_id) != len(assessments) or set(by_id) != set(settings.enabled_strategies):
        raise ValueError("assessments must match configured strategies exactly")
    observations = {(item.symbol, item.snapshot_id, item.source_feature_timestamp, item.generated_at)
                    for item in assessments}
    if len(observations) != 1:
        raise ValueError("cannot combine different feature observations or evaluation times")
    ready = tuple(by_id[key] for key in settings.enabled_strategies
                  if by_id[key].readiness == StrategyReadiness.READY)
    if not ready:
        state = unavailable_state([item.readiness for item in assessments])
        return Consensus(state, None, None, None, StrategyDirection.NEUTRAL, (), ("no_ready_strategies",))
    configured_weight = sum((settings.weight(key) for key in settings.enabled_strategies), Decimal(0))
    ready_weight = sum((settings.weight(item.strategy_id) for item in ready), Decimal(0))
    net = sum((settings.weight(item.strategy_id) * item.score for item in ready), Decimal(0))
    gross = sum((settings.weight(item.strategy_id) * abs(item.score) for item in ready), Decimal(0))
    score = net / ready_weight
    agreement = abs(net) / gross if gross else Decimal(0)
    confidence = sum((settings.weight(item.strategy_id) * item.confidence for item in ready), Decimal(0))
    confidence = confidence / configured_weight * agreement
    reasons = []
    if len(ready) != len(assessments):
        reasons.append("incomplete_strategy_coverage")
    if gross and agreement < 1:
        reasons.append("opposing_strategy_evidence")
    if abs(score) < settings.candidate_score_threshold:
        reasons.append("below_candidate_score")
    if confidence < settings.min_candidate_confidence:
        reasons.append("below_candidate_confidence")
    direction = StrategyDirection.NEUTRAL
    contributors = ()
    if abs(score) >= settings.candidate_score_threshold and confidence >= settings.min_candidate_confidence:
        direction = StrategyDirection.LONG if score > 0 else StrategyDirection.SHORT
        contributors = tuple(item.strategy_id for item in ready if sign(item.score) == sign(score))
        reasons.append("candidate_thresholds_met")
    return Consensus(StrategyReadiness.READY, score, confidence, agreement, direction,
                     contributors, tuple(reasons))


class StrategyEngine:
    """Pure evaluate() plus synchronous reads of an injected FeatureProvider.

    evaluate(snapshot) uses the snapshot's as-of time for reproducible replay.
    latest/status instead use the injected wall clock to reject stale snapshots.
    There is no evaluation loop, mutable history, cache, or lifecycle task.
    """

    def __init__(self, source: FeatureProvider | None = None, settings: StrategySettings | None = None,
                 *, symbols: Sequence[str] = (), clock: Callable[[], datetime] | None = None) -> None:
        self.settings = StrategySettings.model_validate(settings) if settings is not None else StrategySettings()
        self._source = source
        self._symbols = tuple(symbols)
        if len(set(self._symbols)) != len(self._symbols) or any(
                not symbol or symbol != symbol.strip().upper() for symbol in self._symbols):
            raise ValueError("symbols must be unique, nonempty, uppercase values")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        available: tuple[Strategy, ...] = (TrendFollowing(), MomentumContinuation(), MeanReversion())
        by_id = {strategy.strategy_id: strategy for strategy in available}
        self.strategies = tuple(by_id[key] for key in self.settings.enabled_strategies)
        self.settings_id = identity("settings", self.settings)
        self._groups = tuple(sorted({name for strategy in self.strategies
                                   for name in strategy.required_feature_groups + strategy.optional_feature_groups}))

    def evaluate(self, snapshot: FeatureSnapshot, *, now: datetime | None = None) -> StrategySnapshot:
        snapshot = FeatureSnapshot.model_validate(snapshot)
        evaluated_at = snapshot.generated_at if now is None else now
        assessments = tuple(strategy.evaluate(snapshot, self.settings, now=evaluated_at)
                            for strategy in self.strategies)
        consensus = aggregate(assessments, self.settings)
        snapshot_id = snapshot_identity(snapshot)
        observation_id = observation_identity(snapshot, self._groups)
        candidate = None
        if consensus.direction != StrategyDirection.NEUTRAL:
            candidate = StrategyCandidate(
                candidate_id=identity("candidate", (ENGINE_VERSION, self.settings_id, observation_id,
                                                    consensus.direction)),
                symbol=snapshot.symbol, generated_at=evaluated_at, snapshot_id=snapshot_id,
                observation_id=observation_id, direction=consensus.direction,
                composite_score=consensus.score, confidence=consensus.confidence,
                contributing_strategies=consensus.contributors, reasons=consensus.reasons,
            )
        return StrategySnapshot(symbol=snapshot.symbol, generated_at=evaluated_at,
            source_feature_timestamp=snapshot.generated_at, snapshot_id=snapshot_id,
            observation_id=observation_id, settings_id=self.settings_id, engine_version=ENGINE_VERSION,
            assessments=assessments, readiness=consensus.readiness, direction=consensus.direction,
            composite_score=consensus.score, confidence=consensus.confidence, agreement=consensus.agreement,
            reasons=consensus.reasons, candidate=candidate)

    def latest(self, symbol: str) -> StrategySnapshot:
        if symbol not in self._symbols:
            raise KeyError(symbol)
        if self._source is None:
            raise RuntimeError("feature provider is not configured")
        snapshot = self._source.latest(symbol)
        if snapshot.symbol != symbol:
            raise ValueError("feature provider returned a different symbol")
        return self.evaluate(snapshot, now=self._clock())

    def status(self) -> StrategyEngineStatus:
        statuses = []
        for symbol in self._symbols:
            snapshot = self.latest(symbol)
            statuses.append(StrategySymbolStatus(symbol=symbol, readiness=snapshot.readiness,
                direction=snapshot.direction, snapshot_id=snapshot.snapshot_id,
                candidate_available=snapshot.candidate is not None))
        return StrategyEngineStatus(generated_at=self._clock(), engine_version=ENGINE_VERSION,
            settings_id=self.settings_id, strategies=tuple(strategy.definition(self.settings)
                for strategy in self.strategies), symbols=tuple(statuses))
