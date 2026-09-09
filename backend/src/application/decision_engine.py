"""On-demand eligibility policy over typed strategy output; no execution."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
from typing import Protocol

from pydantic import TypeAdapter

from src.application.decision_identity import DECISION_ENGINE_VERSION, decision_identity, policy_identity
from src.application.decision_settings import DecisionSettings
from src.application.decision_validation import (
    aware_time, coherence_issues, incomplete_coverage, source_identity, validated_snapshot,
)
from src.domain.decisions import (
    DecisionEngineStatus, DecisionOutcome, DecisionPolicy, DecisionReadiness, DecisionReason,
    DecisionReasonCode as Code, DecisionRecord, DecisionSymbol, DecisionSymbolStatus,
)
from src.domain.strategies import StrategyDirection, StrategyReadiness, StrategySnapshot


class StrategyProvider(Protocol):
    def latest(self, symbol: str) -> StrategySnapshot: ...


class DecisionSourceError(RuntimeError):
    """The provider could not supply enough valid metadata for a safe record."""


def _age(now: datetime, timestamp: datetime) -> Decimal:
    delta = now - timestamp
    with localcontext(Context(prec=34)):
        return Decimal(delta.days) * 86400 + delta.seconds + Decimal(delta.microseconds) / 1_000_000


class DecisionEngine:
    def __init__(self, source: StrategyProvider | None = None, settings: DecisionSettings | None = None,
                 *, symbols: Sequence[str] = (), clock: Callable[[], datetime] | None = None) -> None:
        self.settings = DecisionSettings.model_validate(settings) if settings is not None else DecisionSettings()
        self._symbols = tuple(TypeAdapter(DecisionSymbol).validate_python(symbol) for symbol in symbols)
        if len(set(self._symbols)) != len(self._symbols):
            raise ValueError("symbols must be unique")
        self._source = source
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.policy_id = policy_identity(self.settings, self._symbols)

    def evaluate(self, snapshot: StrategySnapshot, *, now: datetime) -> DecisionRecord:
        """Same snapshot, policy and explicit time yield the same immutable record."""
        if aware_time(now) is None:
            raise ValueError("now must be a timezone-aware datetime")
        metadata = source_identity(snapshot)
        strategy_time = aware_time(getattr(snapshot, "generated_at", None))
        feature_time = aware_time(getattr(snapshot, "source_feature_timestamp", None))
        source = validated_snapshot(snapshot)
        incomplete = incomplete_coverage(snapshot)
        reasons: list[DecisionReason] = []

        def add(code: Code, observed: Decimal | None = None, threshold: Decimal | None = None) -> None:
            if not any(item.code == code for item in reasons):
                reasons.append(DecisionReason(code=code, observed=observed, threshold=threshold))

        invalid = source is None or strategy_time is None or feature_time is None
        if invalid:
            add(Code.INVALID_STRATEGY_SNAPSHOT)
        elif issues := coherence_issues(source):
            invalid = True
            for code in issues:
                add(code)
        if incomplete:
            add(Code.INCOMPLETE_STRATEGY_COVERAGE)
        unsupported = bool(self._symbols and metadata.symbol not in self._symbols)
        if unsupported:
            add(Code.UNSUPPORTED_SYMBOL)

        stale = False
        maximum = self.settings.max_strategy_snapshot_age_seconds
        for timestamp, code in ((strategy_time, Code.SNAPSHOT_TOO_OLD), (feature_time, Code.FEATURE_TOO_OLD)):
            if timestamp is not None:
                age = _age(now, timestamp)
                if age < 0:
                    stale = True
                    add(Code.FUTURE_TIMESTAMP)
                elif age >= maximum:
                    stale = True
                    add(code, age, maximum)
        if strategy_time is not None and feature_time is not None and strategy_time < feature_time:
            stale = True
            add(Code.TIMESTAMP_MISMATCH)
        if source is not None:
            if source.readiness == StrategyReadiness.STALE:
                stale = True
                add(Code.SOURCE_STALE)
            if source.candidate is not None and source.candidate.generated_at > now:
                stale = True
                add(Code.FUTURE_TIMESTAMP)
        # Missing source times are not invented, including for invalid copies.
        if strategy_time is None or feature_time is None:
            readiness = DecisionReadiness.UNAVAILABLE
        elif stale:
            readiness = DecisionReadiness.STALE
        else:
            readiness = DecisionReadiness.UNAVAILABLE if invalid else DecisionReadiness.READY
        candidate = None if invalid else source.candidate
        agreement = None if invalid else source.agreement
        blocked = invalid or stale or unsupported

        if not blocked and source.readiness != StrategyReadiness.READY:
            readiness = DecisionReadiness.UNAVAILABLE
            add(Code.SOURCE_WARMING_UP if source.readiness == StrategyReadiness.WARMING_UP else Code.SOURCE_UNAVAILABLE)
        if candidate is not None and not blocked:
            if source.readiness != StrategyReadiness.READY:
                blocked = True
            if source.agreement < self.settings.min_decision_agreement:
                blocked = True
                add(Code.INSUFFICIENT_AGREEMENT, source.agreement, self.settings.min_decision_agreement)
            count = len(candidate.contributing_strategies)
            if count < self.settings.min_contributing_strategies:
                blocked = True
                add(Code.INSUFFICIENT_CONTRIBUTORS, Decimal(count), Decimal(self.settings.min_contributing_strategies))
            if incomplete and self.settings.block_incomplete_strategy_coverage:
                blocked = True
                add(Code.INCOMPLETE_COVERAGE_BLOCKED)

        if blocked:
            outcome = DecisionOutcome.BLOCKED
        elif candidate is None:
            outcome = DecisionOutcome.NO_ACTION
            add(Code.NO_CANDIDATE)
        else:
            outcome = DecisionOutcome.ELIGIBLE
            add(Code.ELIGIBILITY_CHECKS_PASSED)
        candidate_id = candidate.candidate_id if candidate else None
        return DecisionRecord(**metadata.model_dump(), generated_at=now,
            source_strategy_timestamp=strategy_time, source_feature_timestamp=feature_time,
            decision_id=decision_identity(policy_id=self.policy_id, symbol=metadata.symbol,
                observation_id=metadata.observation_id, candidate_id=candidate_id, outcome=outcome,
                strategy_settings_id=metadata.strategy_settings_id, strategy_engine_version=metadata.strategy_engine_version),
            candidate_id=candidate_id, direction=candidate.direction if candidate else StrategyDirection.NEUTRAL,
            outcome=outcome, readiness=readiness,
            composite_score=candidate.composite_score if candidate else None,
            confidence=candidate.confidence if candidate else None, agreement=agreement,
            contributing_strategies=candidate.contributing_strategies if candidate else (),
            incomplete_strategy_coverage=incomplete, reasons=tuple(reasons),
            policy_id=self.policy_id, engine_version=DECISION_ENGINE_VERSION)

    def latest(self, symbol: str) -> DecisionRecord:
        if symbol not in self._symbols:
            raise KeyError(symbol)
        if self._source is None:
            raise DecisionSourceError("Strategy source is not configured")
        try:
            snapshot = self._source.latest(symbol)
            if not isinstance(snapshot, StrategySnapshot) or snapshot.symbol != symbol:
                raise ValueError("provider symbol mismatch")
            return self.evaluate(snapshot, now=self._clock())
        except Exception:
            raise DecisionSourceError("Strategy source cannot provide a safe decision") from None

    def status(self) -> DecisionEngineStatus:
        results = tuple(self.latest(symbol) for symbol in self._symbols)
        return DecisionEngineStatus(generated_at=self._clock(), engine_version=DECISION_ENGINE_VERSION,
            policy_id=self.policy_id, policy=DecisionPolicy.model_validate(self.settings),
            symbols=tuple(DecisionSymbolStatus(symbol=item.symbol, decision_id=item.decision_id,
                candidate_id=item.candidate_id, outcome=item.outcome, readiness=item.readiness,
                direction=item.direction, reasons=item.reasons) for item in results))
