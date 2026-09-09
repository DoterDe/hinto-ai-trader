"""Independent typed consensus fixtures; policy expectations never use policy code."""

from decimal import Decimal

from src.domain.strategies import StrategyAssessment, StrategyCandidate, StrategyEvidence, StrategyId, StrategySnapshot
from src.strategies.identity import identity
from strategy_fixtures import NOW


def strategy_snapshot(*, count: int = 2, agreement: str = "1", incomplete: bool = False,
                      candidate: bool = True, symbol: str = "BTCUSDT", direction: int = 1) -> StrategySnapshot:
    assessments = []
    for key in tuple(StrategyId)[:count]:
        assessments.append(StrategyAssessment(strategy_id=key, symbol=symbol, generated_at=NOW,
            source_feature_timestamp=NOW, snapshot_id="features_fixed", direction="LONG" if direction > 0 else "SHORT",
            score=90 * direction, confidence="0.9", readiness="ready", reasons=(), required_feature_groups=("momentum",),
            evidence=(StrategyEvidence(name="independent_evidence", value=direction, normalized=direction,
                weight=90, contribution=90 * direction, code="fixture"),)))
    reasons = ("incomplete_strategy_coverage",) if incomplete else ()
    if incomplete:
        assessments.append(StrategyAssessment(strategy_id=StrategyId.MEAN_REVERSION, symbol=symbol,
            generated_at=NOW, source_feature_timestamp=NOW, snapshot_id="features_fixed", direction="NEUTRAL",
            score=None, confidence=None, readiness="unavailable", reasons=("missing",), required_feature_groups=("regime",)))
    result_direction = "LONG" if direction > 0 else "SHORT"
    source_confidence = Decimal("0.6") if incomplete else Decimal("0.9")
    if candidate:
        reasons += ("candidate_thresholds_met",)
        item = StrategyCandidate(candidate_id=identity("candidate", ("strategy-engine-v1", "settings_fixed", "observation_fixed", result_direction)),
            symbol=symbol, generated_at=NOW, snapshot_id="features_fixed", observation_id="observation_fixed",
            direction=result_direction, composite_score=90 * direction, confidence=source_confidence,
            contributing_strategies=tuple(item.strategy_id for item in assessments[:count]), reasons=reasons)
    else:
        item = None
        reasons += ("below_candidate_confidence",)
        result_direction = "NEUTRAL"
    return StrategySnapshot(symbol=symbol, generated_at=NOW, source_feature_timestamp=NOW,
        snapshot_id="features_fixed", observation_id="observation_fixed", settings_id="settings_fixed",
        engine_version="strategy-engine-v1", assessments=tuple(assessments), readiness="ready",
        direction=result_direction, composite_score=90 * direction, confidence=source_confidence,
        agreement=agreement, reasons=reasons, candidate=item)
