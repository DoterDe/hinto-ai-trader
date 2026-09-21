"""Classify current production feature evidence, then describe fixed cohorts."""

from datetime import datetime
from decimal import Decimal

from src.application.backtest_math import arithmetic
from src.application.validation_metrics import validation_metrics
from src.domain.backtesting import BacktestSignalOutcome, HistoricalDecision
from src.domain.features import FeatureSnapshot
from src.domain.validation_regimes import (
    TRENDS, VOLATILITIES, RegimeAnalysis, RegimeAssignment, RegimeDefinition, RegimeGroup, SampleSummary,
)
from src.strategies.identity import identity


def assign_regime(snapshot: FeatureSnapshot, boundary: datetime) -> RegimeAssignment:
    """No outcome/history argument: all numerical evidence comes from this frame.

    Trend uses signed normalized EMA separation and directional efficiency.
    Volatility uses trailing ATR/close, not a future/global percentile.
    Unknown dependencies do not invalidate an independently available bucket.
    """
    snapshot = FeatureSnapshot.model_validate(snapshot)
    definition = RegimeDefinition()
    reasons = []
    trend = volatility = "UNKNOWN"
    separation = efficiency = atr = None
    if snapshot.closed_candle_time != boundary or snapshot.generated_at != boundary:
        reasons.append("EVIDENCE_BOUNDARY_MISMATCH")
    else:
        if snapshot.regime.values is None:
            reasons.append("TREND_EVIDENCE_UNAVAILABLE")
        else:
            separation = snapshot.regime.values.normalized_ema_separation
            efficiency = snapshot.regime.values.directional_efficiency
            trend = "RANGE"
            if separation.copy_abs() > definition.ema_separation_deadband and efficiency >= definition.directional_efficiency_floor:
                trend = "UPTREND" if separation > 0 else "DOWNTREND"
        if snapshot.volatility.values is None:
            reasons.append("VOLATILITY_EVIDENCE_UNAVAILABLE")
        else:
            atr = snapshot.volatility.values.normalized_atr
            volatility = ("LOW" if atr <= definition.normalized_atr_low_upper else
                          "MEDIUM" if atr <= definition.normalized_atr_medium_upper else "HIGH")
    payload = dict(definition_id=identity("regime_definition", definition), symbol=snapshot.symbol,
        boundary=boundary, evidence_boundary=snapshot.closed_candle_time, trend=trend, volatility=volatility,
        normalized_ema_separation=separation, directional_efficiency=efficiency, normalized_atr=atr,
        unknown_reasons=tuple(reasons))
    return RegimeAssignment(assignment_id=identity("regime_assignment", payload), **payload)


@arithmetic
def sample_summary(values) -> SampleSummary:
    values = tuple(sorted(value for value in values if value is not None))
    return SampleSummary(count=len(values), minimum=min(values) if values else None,
                         maximum=max(values) if values else None,
                         mean=sum(values, Decimal(0)) / len(values) if values else None)


def analyze_regimes(observations: tuple[HistoricalDecision, ...], outcomes: tuple[BacktestSignalOutcome, ...],
                    assignments: tuple[RegimeAssignment, ...], *, symbols: tuple[str, ...],
                    cutoff: datetime | None = None, cutoffs: dict[str, datetime] | None = None) -> RegimeAnalysis:
    definition = RegimeDefinition()
    definition_id = identity("regime_definition", definition)
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("regime scope must be nonempty and unique")
    # Validate the entire population before selecting cohorts (no silent drops).
    validation_metrics(observations, outcomes, cutoff=cutoff, cutoffs=cutoffs)
    by_key = {}
    for item in assignments:
        item = RegimeAssignment.model_validate(item)
        if (item.definition_id != definition_id or
                item.assignment_id != identity("regime_assignment", item.model_dump(exclude={"assignment_id"}))):
            raise ValueError("invalid regime assignment identity")
        key = (item.symbol, item.boundary)
        if key in by_key:
            raise ValueError("duplicate regime evidence")
        by_key[key] = item
    keys = {(item.decision.symbol, item.source_bar_close_time) for item in observations}
    if len(keys) != len(observations) or keys != set(by_key) or any(symbol not in symbols for symbol, _ in keys):
        raise ValueError("regime evidence must match captured decisions exactly")
    groups = []
    for dimension, labels in (("symbol", sorted(symbols)), ("trend", TRENDS), ("volatility", VOLATILITIES)):
        for label in labels:
            selected = tuple(item for item in observations if (
                item.decision.symbol if dimension == "symbol" else
                getattr(by_key[(item.decision.symbol, item.source_bar_close_time)], dimension)) == label)
            ids = {item.decision.decision_id for item in selected}
            metrics = validation_metrics(selected, (item for item in outcomes if item.decision_id in ids), cutoff=cutoff, cutoffs=cutoffs)
            warnings = []
            if not selected:
                warnings.append("EMPTY_GROUP")
            if metrics.completed_count < definition.minimum_completed_samples:
                warnings.append("SMALL_SAMPLE")
            if metrics.incomplete_count:
                warnings.append("INCOMPLETE_OUTCOMES")
            groups.append(RegimeGroup(dimension=dimension, key=label, metrics=metrics,
                confidence=sample_summary(item.decision.confidence for item in selected),
                composite_score=sample_summary(item.decision.composite_score for item in selected), warnings=tuple(warnings)))
    return RegimeAnalysis(definition_id=definition_id, definition=definition, groups=tuple(groups))
