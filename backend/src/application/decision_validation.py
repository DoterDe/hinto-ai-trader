"""Validate source coherence without recalculating strategy scores."""

from datetime import datetime
from decimal import DecimalException

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from src.domain.decisions import DecisionModel, DecisionReasonCode, DecisionSymbol
from src.domain.models import Identifier
from src.domain.strategies import StrategyReadiness, StrategySnapshot
from src.strategies.identity import identity


class SourceIdentity(DecisionModel):
    symbol: DecisionSymbol
    strategy_snapshot_id: Identifier
    observation_id: Identifier
    strategy_settings_id: Identifier
    strategy_engine_version: Identifier


def aware_time(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    try:
        return TypeAdapter(AwareDatetime).validate_python(value)
    except (ValueError, TypeError):
        return None


def source_identity(snapshot: StrategySnapshot) -> SourceIdentity:
    if not isinstance(snapshot, StrategySnapshot):
        raise TypeError("source must be a StrategySnapshot")
    try:
        return SourceIdentity(symbol=getattr(snapshot, "symbol", None),
            strategy_snapshot_id=getattr(snapshot, "snapshot_id", None),
            observation_id=getattr(snapshot, "observation_id", None),
            strategy_settings_id=getattr(snapshot, "settings_id", None),
            strategy_engine_version=getattr(snapshot, "engine_version", None))
    except ValidationError:
        # Do not fabricate a symbol/identity or return validation payload text.
        raise ValueError("source identifiers cannot form a safe decision record") from None


def validated_snapshot(snapshot: StrategySnapshot) -> StrategySnapshot | None:
    candidate = getattr(snapshot, "candidate", None)
    if candidate is not None and aware_time(getattr(candidate, "generated_at", None)) is None:
        return None
    assessments = getattr(snapshot, "assessments", ())
    if not isinstance(assessments, (tuple, list)) or any(
            aware_time(getattr(item, "generated_at", None)) is None
            or aware_time(getattr(item, "source_feature_timestamp", None)) is None for item in assessments):
        return None
    try:
        return StrategySnapshot.model_validate(snapshot)
    except (ValidationError, DecimalException, ValueError):
        return None


def incomplete_coverage(snapshot: StrategySnapshot) -> bool:
    reasons = getattr(snapshot, "reasons", ())
    return isinstance(reasons, (tuple, list)) and "incomplete_strategy_coverage" in reasons


def coherence_issues(snapshot: StrategySnapshot) -> tuple[DecisionReasonCode, ...]:
    """Additional guarantees not enforced by the Phase 4 value model itself."""
    issues = []
    if not snapshot.assessments:
        issues.append(DecisionReasonCode.INVALID_STRATEGY_SNAPSHOT)
    candidate = snapshot.candidate
    if candidate is None:
        return tuple(issues)
    if candidate.generated_at != snapshot.generated_at:
        issues.append(DecisionReasonCode.TIMESTAMP_MISMATCH)
    expected_id = identity("candidate", (snapshot.engine_version, snapshot.settings_id,
                                         snapshot.observation_id, candidate.direction))
    if candidate.candidate_id != expected_id:
        issues.append(DecisionReasonCode.CANDIDATE_ID_MISMATCH)
    if (candidate.symbol != snapshot.symbol or candidate.snapshot_id != snapshot.snapshot_id
            or candidate.observation_id != snapshot.observation_id
            or candidate.direction != snapshot.direction
            or candidate.composite_score != snapshot.composite_score or candidate.confidence != snapshot.confidence):
        issues.append(DecisionReasonCode.CANDIDATE_SOURCE_MISMATCH)
    agreeing = {item.strategy_id for item in snapshot.assessments
                if item.readiness == StrategyReadiness.READY and item.score != 0
                and (item.score > 0) == (candidate.composite_score > 0)}
    if set(candidate.contributing_strategies) != agreeing:
        issues.append(DecisionReasonCode.INVALID_CONTRIBUTORS)
    incomplete = any(item.readiness != StrategyReadiness.READY for item in snapshot.assessments)
    threshold_failures = {"below_candidate_score", "below_candidate_confidence"}
    if ("candidate_thresholds_met" not in snapshot.reasons
            or "candidate_thresholds_met" not in candidate.reasons
            or threshold_failures.intersection(snapshot.reasons)
            or threshold_failures.intersection(candidate.reasons)
            or incomplete != incomplete_coverage(snapshot)
            or incomplete != ("incomplete_strategy_coverage" in candidate.reasons)
            or candidate.confidence <= 0 or snapshot.agreement <= 0):
        issues.append(DecisionReasonCode.INVALID_CANDIDATE_PROVENANCE)
    return tuple(issues)
