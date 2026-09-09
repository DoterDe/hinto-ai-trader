"""Immutable analytical eligibility records and explicit policy contracts."""

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from src.domain.models import DomainModel, Identifier
from src.domain.strategies import Confidence, Score, StrategyDirection, StrategyId

DecisionSymbol = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{3,32}$", strict=True)]


class DecisionOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    NO_ACTION = "NO_ACTION"


class DecisionReadiness(str, Enum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class DecisionReasonCode(str, Enum):
    ELIGIBILITY_CHECKS_PASSED = "eligibility_checks_passed"
    NO_CANDIDATE = "no_candidate"
    INVALID_STRATEGY_SNAPSHOT = "invalid_strategy_snapshot"
    SOURCE_STALE = "source_stale"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_WARMING_UP = "source_warming_up"
    SNAPSHOT_TOO_OLD = "snapshot_too_old"
    FEATURE_TOO_OLD = "feature_too_old"
    FUTURE_TIMESTAMP = "future_timestamp"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"
    CANDIDATE_ID_MISMATCH = "candidate_id_mismatch"
    CANDIDATE_SOURCE_MISMATCH = "candidate_source_mismatch"
    INVALID_CONTRIBUTORS = "invalid_contributors"
    INVALID_CANDIDATE_PROVENANCE = "invalid_candidate_provenance"
    INSUFFICIENT_AGREEMENT = "insufficient_agreement"
    INSUFFICIENT_CONTRIBUTORS = "insufficient_contributors"
    INCOMPLETE_STRATEGY_COVERAGE = "incomplete_strategy_coverage"
    INCOMPLETE_COVERAGE_BLOCKED = "incomplete_coverage_blocked"
    UNSUPPORTED_SYMBOL = "unsupported_symbol"


class DecisionModel(DomainModel):
    model_config = ConfigDict(extra="forbid")


class DecisionReason(DecisionModel):
    code: DecisionReasonCode
    observed: Decimal | None = None
    threshold: Decimal | None = None


class DecisionPolicy(DecisionModel):
    max_strategy_snapshot_age_seconds: Annotated[Decimal, Field(gt=0)] = Decimal(10)
    min_decision_agreement: Confidence = Decimal("0.50")
    min_contributing_strategies: Annotated[int, Field(strict=True, ge=1, le=len(StrategyId))] = 2
    block_incomplete_strategy_coverage: Annotated[bool, Field(strict=True)] = False


class DecisionRecord(DecisionModel):
    decision_id: Identifier
    symbol: DecisionSymbol
    generated_at: AwareDatetime
    # Invalid source times are omitted in malformed-source diagnostics only.
    source_strategy_timestamp: AwareDatetime | None
    source_feature_timestamp: AwareDatetime | None
    strategy_snapshot_id: Identifier
    observation_id: Identifier
    strategy_settings_id: Identifier
    strategy_engine_version: Identifier
    candidate_id: Identifier | None
    direction: StrategyDirection
    outcome: DecisionOutcome
    readiness: DecisionReadiness
    composite_score: Score | None
    confidence: Confidence | None
    agreement: Confidence | None
    contributing_strategies: Annotated[tuple[StrategyId, ...], Field(max_length=len(StrategyId))]
    incomplete_strategy_coverage: Annotated[bool, Field(strict=True)]
    reasons: Annotated[tuple[DecisionReason, ...], Field(min_length=1, max_length=20)]
    policy_id: Identifier
    engine_version: Identifier

    @model_validator(mode="after")
    def coherent_outcome(self) -> Self:
        codes = tuple(reason.code for reason in self.reasons)
        if len(set(codes)) != len(codes):
            raise ValueError("decision reason codes must be unique")
        if len(set(self.contributing_strategies)) != len(self.contributing_strategies):
            raise ValueError("contributors must be unique")
        if self.candidate_id is None:
            if (self.composite_score is not None or self.confidence is not None
                    or self.contributing_strategies or self.direction != StrategyDirection.NEUTRAL):
                raise ValueError("no candidate requires null values and neutral direction")
        else:
            if (self.composite_score is None or self.confidence is None or self.agreement is None
                    or not self.contributing_strategies or self.direction == StrategyDirection.NEUTRAL
                    or self.composite_score == 0
                    or (self.composite_score > 0) != (self.direction == StrategyDirection.LONG)):
                raise ValueError("candidate values and direction must be coherent")
        if self.outcome == DecisionOutcome.ELIGIBLE:
            if (self.readiness != DecisionReadiness.READY or self.candidate_id is None
                    or self.confidence <= 0 or self.agreement <= 0
                    or DecisionReasonCode.ELIGIBILITY_CHECKS_PASSED not in codes):
                raise ValueError("eligible requires a ready candidate and successful checks")
            if set(codes) - {DecisionReasonCode.ELIGIBILITY_CHECKS_PASSED,
                             DecisionReasonCode.INCOMPLETE_STRATEGY_COVERAGE}:
                raise ValueError("eligible records cannot contain blocking reasons")
        elif DecisionReasonCode.ELIGIBILITY_CHECKS_PASSED in codes:
            raise ValueError("only eligible records may claim successful checks")
        if self.outcome == DecisionOutcome.BLOCKED and not set(codes) - {
                DecisionReasonCode.NO_CANDIDATE, DecisionReasonCode.INCOMPLETE_STRATEGY_COVERAGE}:
            raise ValueError("blocked records require a blocking reason")
        if self.outcome == DecisionOutcome.NO_ACTION:
            if (self.candidate_id is not None or self.readiness == DecisionReadiness.STALE
                    or DecisionReasonCode.NO_CANDIDATE not in codes):
                raise ValueError("no action requires a non-stale source without candidate")
            if set(codes) - {DecisionReasonCode.NO_CANDIDATE, DecisionReasonCode.SOURCE_UNAVAILABLE,
                             DecisionReasonCode.SOURCE_WARMING_UP, DecisionReasonCode.INCOMPLETE_STRATEGY_COVERAGE}:
                raise ValueError("no-action records cannot contain blocking reasons")
        if self.readiness != DecisionReadiness.UNAVAILABLE:
            if self.source_strategy_timestamp is None or self.source_feature_timestamp is None:
                raise ValueError("valid source timestamps must be retained")
        if self.readiness == DecisionReadiness.READY:
            if not self.source_feature_timestamp <= self.source_strategy_timestamp <= self.generated_at:
                raise ValueError("ready timestamps must be ordered")
        if self.incomplete_strategy_coverage != (DecisionReasonCode.INCOMPLETE_STRATEGY_COVERAGE in codes):
            raise ValueError("incomplete coverage provenance must remain visible")
        return self


class DecisionSymbolStatus(DecisionModel):
    symbol: DecisionSymbol
    decision_id: Identifier
    candidate_id: Identifier | None
    outcome: DecisionOutcome
    readiness: DecisionReadiness
    direction: StrategyDirection
    reasons: tuple[DecisionReason, ...]


class DecisionEngineStatus(DecisionModel):
    generated_at: AwareDatetime
    engine_version: Identifier
    policy_id: Identifier
    policy: DecisionPolicy
    evaluation_mode: Literal["on_demand"] = "on_demand"
    symbols: tuple[DecisionSymbolStatus, ...]
