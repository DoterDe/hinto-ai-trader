"""Analytical assessments and candidates with no executable order fields."""

from decimal import Context, Decimal, localcontext
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from src.domain.models import DomainModel, Identifier, Symbol

Score = Annotated[Decimal, Field(ge=-100, le=100)]
Confidence = Annotated[Decimal, Field(ge=0, le=1)]
FeatureGroupName = Literal["trend", "momentum", "volatility", "volume", "regime", "microstructure"]


class StrategyDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class StrategyReadiness(str, Enum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    WARMING_UP = "warming_up"


class StrategyId(str, Enum):
    TREND = "trend_following"
    MOMENTUM = "momentum_continuation"
    MEAN_REVERSION = "mean_reversion"


class StrategyModel(DomainModel):
    model_config = ConfigDict(extra="forbid")


class StrategyEvidence(StrategyModel):
    name: Identifier
    value: Decimal | None
    reference: Decimal | None = None
    normalized: Annotated[Decimal, Field(ge=-1, le=1)] | None = None
    weight: Annotated[Decimal, Field(ge=0, le=100)] = Decimal(0)
    multiplier: Confidence = Decimal(1)
    contribution: Score = Decimal(0)
    code: Identifier

    @model_validator(mode="after")
    def contribution_matches_evidence(self) -> Self:
        with localcontext(Context(prec=34)):
            expected = self.weight * (self.normalized or Decimal(0)) * self.multiplier
        if self.contribution != expected:
            raise ValueError("contribution must equal weight * normalized * multiplier")
        if self.weight and (self.value is None or self.normalized is None):
            raise ValueError("directional evidence requires a value and normalization")
        return self


class StrategyAssessment(StrategyModel):
    strategy_id: StrategyId
    symbol: Symbol
    generated_at: AwareDatetime
    source_feature_timestamp: AwareDatetime
    snapshot_id: Identifier
    direction: StrategyDirection
    score: Score | None
    confidence: Confidence | None
    readiness: StrategyReadiness
    reasons: tuple[str, ...]
    required_feature_groups: tuple[FeatureGroupName, ...]
    optional_feature_groups: tuple[FeatureGroupName, ...] = ()
    evidence: tuple[StrategyEvidence, ...] = ()

    @model_validator(mode="after")
    def coherent_assessment(self) -> Self:
        if self.readiness == StrategyReadiness.READY and self.generated_at < self.source_feature_timestamp:
            raise ValueError("assessment cannot precede its source snapshot")
        if self.readiness == StrategyReadiness.READY:
            if self.score is None or self.confidence is None:
                raise ValueError("ready assessments require score and confidence")
            with localcontext(Context(prec=34)):
                total = sum((item.contribution for item in self.evidence), Decimal(0))
            if self.score != total:
                raise ValueError("score must equal the evidence contributions")
            if self.direction == StrategyDirection.LONG and self.score <= 0:
                raise ValueError("LONG requires a positive score")
            if self.direction == StrategyDirection.SHORT and self.score >= 0:
                raise ValueError("SHORT requires a negative score")
        elif (self.score is not None or self.confidence is not None
              or self.direction != StrategyDirection.NEUTRAL or not self.reasons
              or any(item.contribution != 0 for item in self.evidence)):
            raise ValueError("unready assessments require reasons and no directional score")
        return self


class StrategyCandidate(StrategyModel):
    candidate_id: Identifier
    symbol: Symbol
    generated_at: AwareDatetime
    snapshot_id: Identifier
    observation_id: Identifier
    direction: StrategyDirection
    composite_score: Score
    confidence: Confidence
    contributing_strategies: tuple[StrategyId, ...]
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def analytical_direction(self) -> Self:
        if not self.contributing_strategies or len(set(self.contributing_strategies)) != len(self.contributing_strategies):
            raise ValueError("candidate requires unique contributing strategies")
        if self.direction == StrategyDirection.NEUTRAL:
            raise ValueError("neutral results have no candidate")
        if (self.direction == StrategyDirection.LONG) != (self.composite_score > 0) or self.composite_score == 0:
            raise ValueError("candidate direction must match its score")
        return self


class StrategySnapshot(StrategyModel):
    symbol: Symbol
    generated_at: AwareDatetime
    source_feature_timestamp: AwareDatetime
    snapshot_id: Identifier
    observation_id: Identifier
    settings_id: Identifier
    engine_version: str
    assessments: tuple[StrategyAssessment, ...]
    readiness: StrategyReadiness
    direction: StrategyDirection
    composite_score: Score | None
    confidence: Confidence | None
    agreement: Confidence | None
    reasons: tuple[str, ...]
    candidate: StrategyCandidate | None

    @model_validator(mode="after")
    def coherent_aggregate(self) -> Self:
        if len({item.strategy_id for item in self.assessments}) != len(self.assessments):
            raise ValueError("strategy assessments must be unique")
        if any(item.symbol != self.symbol or item.snapshot_id != self.snapshot_id
               or item.generated_at != self.generated_at
               or item.source_feature_timestamp != self.source_feature_timestamp
               for item in self.assessments):
            raise ValueError("assessments must describe the same source and evaluation")
        ready = any(item.readiness == StrategyReadiness.READY for item in self.assessments)
        if ready != (self.readiness == StrategyReadiness.READY):
            raise ValueError("aggregate readiness requires a ready assessment")
        if ready != all(value is not None for value in (self.composite_score, self.confidence, self.agreement)):
            raise ValueError("only ready aggregates have numeric results")
        if not ready and any(value is not None for value in (self.composite_score, self.confidence, self.agreement)):
            raise ValueError("unready aggregate values must be null")
        if self.candidate is None:
            if self.direction != StrategyDirection.NEUTRAL:
                raise ValueError("a no-candidate result is neutral")
        elif (not ready or self.candidate.direction != self.direction
              or self.candidate.symbol != self.symbol or self.candidate.snapshot_id != self.snapshot_id
              or self.candidate.observation_id != self.observation_id
              or self.candidate.composite_score != self.composite_score
              or self.candidate.confidence != self.confidence):
            raise ValueError("candidate must match its aggregate")
        return self


class StrategyDefinition(StrategyModel):
    strategy_id: StrategyId
    required_feature_groups: tuple[FeatureGroupName, ...]
    optional_feature_groups: tuple[FeatureGroupName, ...]
    aggregation_weight: Annotated[Decimal, Field(gt=0)]


class StrategySymbolStatus(StrategyModel):
    symbol: Symbol
    readiness: StrategyReadiness
    direction: StrategyDirection
    snapshot_id: Identifier
    candidate_available: bool


class StrategyEngineStatus(StrategyModel):
    generated_at: AwareDatetime
    engine_version: str
    settings_id: Identifier
    evaluation_mode: Literal["on_demand"] = "on_demand"
    strategies: tuple[StrategyDefinition, ...]
    symbols: tuple[StrategySymbolStatus, ...]
