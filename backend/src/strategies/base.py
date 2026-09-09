"""Common feature validation, readiness, and auditable assessment assembly."""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal, DecimalException

from src.application.strategy_settings import StrategySettings
from src.domain.features import FeatureSnapshot, Readiness
from src.domain.strategies import (
    FeatureGroupName, StrategyAssessment, StrategyDefinition, StrategyDirection,
    StrategyEvidence, StrategyId, StrategyReadiness,
)
from src.strategies.identity import snapshot_identity
from src.strategies.scoring import arithmetic, linear_quality, number


def unavailable_state(states: list[StrategyReadiness]) -> StrategyReadiness:
    for state in (StrategyReadiness.STALE, StrategyReadiness.UNAVAILABLE, StrategyReadiness.WARMING_UP):
        if state in states:
            return state
    return StrategyReadiness.UNAVAILABLE


def source_issue(snapshot: FeatureSnapshot, name: FeatureGroupName, now: datetime,
                 settings: StrategySettings) -> tuple[StrategyReadiness, str] | None:
    stream = "book_ticker" if name == "microstructure" else f"kline:{snapshot.interval}"
    sources = [source for source in snapshot.sources if source.stream == stream]
    if len(sources) != 1:
        return StrategyReadiness.UNAVAILABLE, "source_metadata_missing"
    source = sources[0]
    if source.stale:
        state = StrategyReadiness.UNAVAILABLE if source.reason == "missing" else StrategyReadiness.STALE
        return state, f"source_{source.reason or 'stale'}"
    if source.event_time is None or source.received_at is None or source.connection_id is None or source.generation is None:
        return StrategyReadiness.UNAVAILABLE, "source_metadata_missing"
    for timestamp in (source.event_time, source.received_at):
        if timestamp > snapshot.generated_at or timestamp > now:
            return StrategyReadiness.STALE, "source_clock_skew"
        if number((now - timestamp).total_seconds()) >= settings.max_feature_age_seconds:
            return StrategyReadiness.STALE, "source_too_old"
    if name != "microstructure" and snapshot.closed_candle_time is not None:
        if snapshot.closed_candle_time > source.event_time or snapshot.closed_candle_time > snapshot.generated_at:
            return StrategyReadiness.STALE, "closed_candle_in_future"
    return None


@arithmetic
def contribution(name: str, value: Decimal, normalized: Decimal, weight: Decimal,
                 multiplier: Decimal = Decimal(1), reference: Decimal | None = None) -> StrategyEvidence:
    return StrategyEvidence(name=name, value=value, reference=reference, normalized=normalized,
                            weight=weight, multiplier=multiplier,
                            contribution=weight * normalized * multiplier, code="directional_contribution")


def context(name: str, value: Decimal | None, normalized: Decimal | None,
            *, reference: Decimal | None = None, code: str = "score_quality") -> StrategyEvidence:
    return StrategyEvidence(name=name, value=value, normalized=normalized, reference=reference, code=code)


def require_range(value: Decimal, low: Decimal, high: Decimal | None = None, *, exclusive_low: bool = False) -> None:
    value = number(value)
    if value < low or (exclusive_low and value == low) or (high is not None and value > high):
        raise ValueError("feature value is outside its semantic range")


@arithmetic
def volatility_quality(snapshot: FeatureSnapshot, settings: StrategySettings) -> tuple[Decimal, StrategyEvidence]:
    atr = snapshot.volatility.values.normalized_atr
    require_range(atr, Decimal(0))
    quality = 1 - linear_quality(atr, settings.atr_soft_limit, settings.atr_hard_limit)
    return quality, context("normalized_atr_quality", atr, quality, reference=settings.atr_hard_limit)


class Strategy(ABC):
    strategy_id: StrategyId
    required_feature_groups: tuple[FeatureGroupName, ...]
    optional_feature_groups: tuple[FeatureGroupName, ...] = ()

    def definition(self, settings: StrategySettings) -> StrategyDefinition:
        return StrategyDefinition(strategy_id=self.strategy_id,
            required_feature_groups=self.required_feature_groups,
            optional_feature_groups=self.optional_feature_groups,
            aggregation_weight=settings.weight(self.strategy_id))

    @arithmetic
    def evaluate(self, snapshot: FeatureSnapshot, settings: StrategySettings,
                 *, now: datetime | None = None) -> StrategyAssessment:
        snapshot = FeatureSnapshot.model_validate(snapshot)
        settings = StrategySettings.model_validate(settings)
        evaluated_at = snapshot.generated_at if now is None else now
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluation time must be timezone-aware")
        metadata = dict(strategy_id=self.strategy_id, symbol=snapshot.symbol, generated_at=evaluated_at,
                        source_feature_timestamp=snapshot.generated_at, snapshot_id=snapshot_identity(snapshot),
                        required_feature_groups=self.required_feature_groups,
                        optional_feature_groups=self.optional_feature_groups)

        def absent(readiness: StrategyReadiness, reasons: tuple[str, ...]) -> StrategyAssessment:
            return StrategyAssessment(**metadata, readiness=readiness, direction=StrategyDirection.NEUTRAL,
                                      score=None, confidence=None, reasons=reasons)

        age = number((evaluated_at - snapshot.generated_at).total_seconds())
        if age < 0:
            return absent(StrategyReadiness.STALE, ("snapshot_clock_skew",))
        if age >= settings.max_feature_age_seconds:
            return absent(StrategyReadiness.STALE, ("snapshot_too_old",))
        states, reasons = [], []
        for name in self.required_feature_groups:
            group = getattr(snapshot, name)
            if group.state != Readiness.READY or group.values is None:
                states.append(StrategyReadiness(group.state.value))
                reasons.extend(f"{name}:{reason}" for reason in group.reasons)
                continue
            issue = source_issue(snapshot, name, evaluated_at, settings)
            if issue is not None:
                states.append(issue[0])
                reasons.append(f"{name}:{issue[1]}")
            if name != "microstructure" and (snapshot.closed_candle_time is None
                    or snapshot.closed_candles < group.required_samples
                    or group.available_samples < group.required_samples):
                states.append(StrategyReadiness.WARMING_UP)
                reasons.append(f"{name}:insufficient_closed_history")
        if states:
            return absent(unavailable_state(states), tuple(reasons))
        try:
            evidence = self.calculate(snapshot, settings)
            quality = Decimal(1)
            optional_reasons = []
            for name in self.optional_feature_groups:
                factor, item, reason = self._optional_quality(snapshot, name, evaluated_at, settings)
                evidence += (item,)
                quality *= factor
                if reason:
                    optional_reasons.append(reason)
            score = sum((item.contribution for item in evidence), Decimal(0))
            magnitude = sum((abs(item.contribution) for item in evidence), Decimal(0))
            agreement = abs(score) / magnitude if magnitude else Decimal(0)
            strength = abs(score) / 100
            confidence = strength * agreement * quality
            direction = StrategyDirection.NEUTRAL
            if abs(score) >= settings.min_absolute_strategy_score:
                direction = StrategyDirection.LONG if score > 0 else StrategyDirection.SHORT
            else:
                optional_reasons.append("below_strategy_dead_zone")
            evidence += (context("score_strength", strength, strength, code="confidence_factor"),
                         context("directional_agreement", agreement, agreement, code="confidence_factor"))
            return StrategyAssessment(**metadata, readiness=StrategyReadiness.READY, direction=direction,
                                      score=score, confidence=confidence, reasons=tuple(optional_reasons),
                                      evidence=evidence)
        except (ValueError, DecimalException, OverflowError, ZeroDivisionError):
            return absent(StrategyReadiness.UNAVAILABLE, ("invalid_feature_values",))

    @staticmethod
    @arithmetic
    def _optional_quality(snapshot: FeatureSnapshot, name: FeatureGroupName, now: datetime,
                          settings: StrategySettings) -> tuple[Decimal, StrategyEvidence, str | None]:
        group = getattr(snapshot, name)
        issue = source_issue(snapshot, name, now, settings)
        if group.state != Readiness.READY or group.values is None or issue is not None:
            reason = f"{name}:optional_{issue[1] if issue else group.state.value}"
            quality = settings.optional_context_missing_quality
            return quality, context("optional_spread_quality", None, quality, code="optional_missing"), reason
        book = group.values
        try:
            require_range(book.spread_bps, Decimal(0))
            require_range(book.bid, Decimal(0), exclusive_low=True)
            require_range(book.ask, book.bid)
        except ValueError:
            quality = settings.optional_context_missing_quality
            return quality, context("optional_spread_quality", None, quality, code="optional_invalid"), f"{name}:optional_invalid"
        quality = 1 - linear_quality(book.spread_bps, 0, settings.max_acceptable_spread_bps)
        return quality, context("optional_spread_quality", book.spread_bps, quality,
                                reference=settings.max_acceptable_spread_bps, code="confidence_factor"), None

    @abstractmethod
    def calculate(self, snapshot: FeatureSnapshot, settings: StrategySettings) -> tuple[StrategyEvidence, ...]:
        """Return bounded weighted contributions plus explicitly named quality factors."""
