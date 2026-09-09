from datetime import timedelta, timezone
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from src.application.strategy_engine import StrategyEngine, aggregate
from src.application.strategy_settings import StrategySettings
from src.domain.features import FeatureSnapshot, Readiness
from src.domain.strategies import StrategyAssessment, StrategyEvidence, StrategyId, StrategySnapshot
from src.strategies.identity import identity
from strategy_fixtures import NOW, features, positive_momentum, positive_trend, state


def assessments(scores: tuple[int | None, ...], confidence: str = "1",
                unready: str = "unavailable") -> tuple[StrategyAssessment, ...]:
    result = []
    for key, score in zip(StrategyId, scores, strict=True):
        evidence = () if score is None else (StrategyEvidence(
            name="independent_fixture", value=score, normalized=Decimal(score) / 100,
            weight=100, contribution=score, code="test_contribution"),)
        result.append(StrategyAssessment(strategy_id=key, symbol="BTCUSDT", generated_at=NOW,
            source_feature_timestamp=NOW, snapshot_id="features_fixed", direction=(
                "NEUTRAL" if score is None or score == 0 else "LONG" if score > 0 else "SHORT"),
            score=score, confidence=None if score is None else confidence,
            readiness=unready if score is None else "ready", reasons=("missing",) if score is None else (),
            required_feature_groups=("momentum",), evidence=evidence))
    return tuple(result)


@pytest.mark.parametrize("scores,score,confidence,agreement,direction", [
    ((100, 100, 100), "100", "1", "1", "LONG"),
    ((-100, -100, -100), "-100", "1", "1", "SHORT"),
    ((60, 60, -30), "30", "0.6", "0.6", "NEUTRAL"),
    ((60, -60, 0), "0", "0", "0", "NEUTRAL"),
    ((0, 0, 0), "0", "0", "0", "NEUTRAL"),
    ((39, 39, 39), "39", "1", "1", "NEUTRAL"),
    ((40, 40, 40), "40", "1", "1", "LONG"),
    ((-40, -40, -40), "-40", "1", "1", "SHORT"),
])
def test_weighted_consensus_examples(scores, score, confidence, agreement, direction) -> None:
    result = aggregate(assessments(scores), StrategySettings())
    assert result.score == Decimal(score)
    assert result.confidence == Decimal(confidence)
    assert result.agreement == Decimal(agreement)
    assert result.direction == direction


@pytest.mark.parametrize("confidence,direction", [("0.54999", "NEUTRAL"), ("0.55", "LONG"), ("0.8", "LONG")])
def test_candidate_confidence_threshold_is_inclusive(confidence: str, direction: str) -> None:
    result = aggregate(assessments((40, 40, 40), confidence), StrategySettings())
    assert result.direction == direction


def test_one_unavailable_retains_independent_candidates_with_coverage_penalty() -> None:
    result = aggregate(assessments((90, 90, None), "0.9"), StrategySettings())
    assert result.score == 90
    assert result.confidence == Decimal("0.6")
    assert result.direction == "LONG"
    assert result.contributors == (StrategyId.TREND, StrategyId.MOMENTUM)
    assert "incomplete_strategy_coverage" in result.reasons


def test_one_ready_is_not_falsely_confident_with_three_configured() -> None:
    result = aggregate(assessments((90, None, None), "0.9"), StrategySettings())
    assert result.score == 90 and result.confidence == Decimal("0.3")
    assert result.direction == "NEUTRAL"


@pytest.mark.parametrize("readiness", ["unavailable", "stale", "warming_up"])
def test_all_unready_have_null_values(readiness: str) -> None:
    result = aggregate(assessments((None, None, None), unready=readiness), StrategySettings())
    assert result.readiness == readiness
    assert result.score is result.confidence is result.agreement is None
    assert result.direction == "NEUTRAL" and not result.contributors


def test_heterogeneous_unready_prioritizes_stale_then_unavailable() -> None:
    items = assessments((None, None, None), unready="warming_up")
    items = (items[0].model_copy(update={"readiness": "stale"}), items[1], items[2])
    assert aggregate(items, StrategySettings()).readiness == "stale"


def test_configured_weights_and_disagreement_are_transparent() -> None:
    result = aggregate(assessments((100, -100, 100)), StrategySettings(trend_weight=2))
    assert result.score == 50 and result.agreement == Decimal("0.5")
    assert result.confidence == Decimal("0.5") and result.direction == "NEUTRAL"
    assert "opposing_strategy_evidence" in result.reasons


def test_contributor_list_excludes_opposing_and_unready_assessments() -> None:
    result = aggregate(assessments((100, 100, -20)), StrategySettings())
    assert result.score == 60 and result.direction == "LONG"
    assert result.contributors == (StrategyId.TREND, StrategyId.MOMENTUM)


def test_ready_neutral_is_included_and_dilutes_score() -> None:
    result = aggregate(assessments((90, 90, 0), "0.9"), StrategySettings())
    assert result.score == 60


def test_assessment_order_does_not_change_weighted_consensus() -> None:
    items = assessments((77, -31, 15), "0.83")
    assert aggregate(items, StrategySettings()) == aggregate(tuple(reversed(items)), StrategySettings())


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "symbol", "source", "timestamp", "evaluation"])
def test_aggregate_rejects_mixed_or_incomplete_inputs(mutation: str) -> None:
    items = assessments((60, 60, 60))
    if mutation == "duplicate":
        items = (items[0], items[0], items[2])
    elif mutation == "missing":
        items = items[:2]
    else:
        updates = {"symbol": {"symbol": "ETHUSDT"}, "source": {"snapshot_id": "different"},
                   "timestamp": {"source_feature_timestamp": NOW - timedelta(seconds=1)},
                   "evaluation": {"generated_at": NOW + timedelta(seconds=1)}}[mutation]
        items = (items[0].model_copy(update=updates), *items[1:])
    with pytest.raises(ValueError):
        aggregate(items, StrategySettings())


def test_engine_evaluation_is_pure_deterministic_and_round_trips() -> None:
    engine = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.MOMENTUM,)))
    snapshot = positive_momentum()
    first = engine.evaluate(snapshot)
    assert first == engine.evaluate(snapshot)
    assert first.candidate is not None and first.candidate.composite_score == 100
    assert first.candidate.confidence == 1
    assert StrategySnapshot.model_validate_json(first.model_dump_json()) == first
    assert first.source_feature_timestamp == first.generated_at == NOW
    assert "quantity" not in first.candidate.model_dump()
    assert "Infinity" not in first.model_dump_json() and "NaN" not in first.model_dump_json()


def test_engine_preserves_each_assessment_without_forcing_consensus() -> None:
    result = StrategyEngine().evaluate(positive_trend())
    assert len(result.assessments) == 3
    assert result.assessments[0].score == 100
    assert result.assessments[1].score == 40
    assert result.assessments[2].score == 0
    assert result.readiness == "ready"
    # Mean score is 140/3; mean confidence 1.4/3 misses .55.
    assert result.candidate is None and result.direction == "NEUTRAL"


def test_engine_respects_independent_dependencies() -> None:
    snapshot = state(positive_momentum(), "trend", Readiness.STALE)
    result = StrategyEngine().evaluate(snapshot)
    assert [item.readiness.value for item in result.assessments] == ["stale", "ready", "stale"]
    assert result.composite_score == 100 and result.readiness == "ready"


@pytest.mark.parametrize("seconds", [-1, 10, 100])
def test_explicit_evaluation_clock_rejects_future_or_stale_snapshot(seconds: int) -> None:
    result = StrategyEngine().evaluate(positive_momentum(), now=NOW + timedelta(seconds=seconds))
    assert result.readiness == "stale" and result.candidate is None
    assert all(item.score is None for item in result.assessments)


def test_repeated_reads_keep_candidate_identity_when_only_read_time_changes() -> None:
    engine = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.TREND,)))
    snapshot = positive_trend()
    first = engine.evaluate(snapshot)
    newer = snapshot.model_copy(update={"generated_at": NOW + timedelta(seconds=1)})
    second = engine.evaluate(newer)
    assert first.snapshot_id != second.snapshot_id
    assert first.observation_id == second.observation_id
    assert first.candidate.candidate_id == second.candidate.candidate_id


@pytest.mark.parametrize("change", ["values", "closed_time", "generation", "settings", "symbol", "history_reset"])
def test_meaningful_inputs_change_candidate_identity(change: str) -> None:
    config = StrategySettings(enabled_strategies=(StrategyId.TREND,))
    snapshot = positive_trend()
    first = StrategyEngine(settings=config).evaluate(snapshot)
    if change == "values":
        group = snapshot.trend.model_copy(update={"values": snapshot.trend.values.model_copy(update={"ema_fast": Decimal(103)})})
        snapshot = snapshot.model_copy(update={"trend": group})
    elif change == "closed_time":
        snapshot = snapshot.model_copy(update={"closed_candle_time": NOW - timedelta(seconds=1)})
    elif change == "generation":
        snapshot = snapshot.model_copy(update={"sources": tuple(item.model_copy(update={"generation": 2}) for item in snapshot.sources)})
    elif change == "settings":
        config = StrategySettings(enabled_strategies=(StrategyId.TREND,), trend_weight=2)
    elif change == "symbol":
        snapshot = snapshot.model_copy(update={"symbol": "ETHUSDT"})
    else:
        snapshot = snapshot.model_copy(update={"history_resets": 1})
    second = StrategyEngine(settings=config).evaluate(snapshot)
    assert first.candidate.candidate_id != second.candidate.candidate_id


def test_unrelated_book_and_open_refresh_do_not_change_trend_observation() -> None:
    engine = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.TREND,)))
    original = positive_trend()
    refreshed = original.model_copy(update={"generated_at": NOW + timedelta(seconds=1),
        "sources": tuple(item.model_copy(update={"event_time": NOW + timedelta(seconds=1),
                                                 "received_at": NOW + timedelta(seconds=1)}) for item in original.sources)})
    assert engine.evaluate(original).observation_id == engine.evaluate(refreshed).observation_id


def test_optional_book_observation_changes_momentum_identity() -> None:
    engine = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.MOMENTUM,)))
    original = positive_momentum()
    refreshed = original.model_copy(update={"sources": tuple(item.model_copy(update={"event_time": NOW - timedelta(milliseconds=1)})
        if item.stream == "book_ticker" else item for item in original.sources)})
    assert engine.evaluate(original).observation_id != engine.evaluate(refreshed).observation_id


def test_identity_is_canonical_and_decimal_context_independent() -> None:
    expected = identity("test", {"v": Decimal("1.0"), "t": NOW})
    with localcontext() as ctx:
        ctx.prec = 2
        assert identity("test", {"t": NOW.astimezone(timezone(timedelta(hours=5))), "v": Decimal("1.000")}) == expected
        assert identity("test", Decimal("-0")) == identity("test", Decimal("0.000"))
    with pytest.raises(ValueError):
        identity("test", Decimal("NaN"))
    with pytest.raises(ValueError):
        identity("test", NOW.replace(tzinfo=None))


def test_engine_does_not_depend_on_ambient_decimal_precision() -> None:
    engine = StrategyEngine()
    expected = engine.evaluate(positive_trend())
    with localcontext() as ctx:
        ctx.prec = 2
        assert engine.evaluate(positive_trend()) == expected


class Provider:
    def __init__(self) -> None:
        self.calls = []
        self.snapshots = {"BTCUSDT": positive_momentum(), "ETHUSDT": features().model_copy(update={"symbol": "ETHUSDT"})}

    def latest(self, symbol: str) -> FeatureSnapshot:
        self.calls.append(symbol)
        return self.snapshots[symbol]


def test_latest_reads_source_once_and_isolates_symbols_without_cache() -> None:
    source = Provider()
    engine = StrategyEngine(source, StrategySettings(enabled_strategies=(StrategyId.MOMENTUM,)),
                            symbols=tuple(source.snapshots), clock=lambda: NOW)
    btc = engine.latest("BTCUSDT")
    eth = engine.latest("ETHUSDT")
    assert btc.candidate is not None and eth.candidate is None
    assert source.calls == ["BTCUSDT", "ETHUSDT"]
    assert engine.latest("BTCUSDT") == btc
    source.snapshots["BTCUSDT"] = features()
    assert engine.latest("BTCUSDT").candidate is None
    with pytest.raises(KeyError):
        engine.latest("UNKNOWN")
    assert "UNKNOWN" not in source.calls


def test_latest_checks_clock_and_provider_symbol() -> None:
    source = Provider()
    engine = StrategyEngine(source, symbols=("BTCUSDT",), clock=lambda: NOW + timedelta(seconds=10))
    assert engine.latest("BTCUSDT").readiness == "stale"
    source.snapshots["BTCUSDT"] = source.snapshots["ETHUSDT"]
    with pytest.raises(ValueError, match="different symbol"):
        engine.latest("BTCUSDT")


def test_status_exposes_definitions_dependencies_and_on_demand_symbol_state() -> None:
    source = Provider()
    engine = StrategyEngine(source, symbols=tuple(source.snapshots), clock=lambda: NOW)
    status = engine.status()
    assert status.evaluation_mode == "on_demand" and len(status.strategies) == 3
    assert status.strategies[0].required_feature_groups == ("trend", "momentum", "regime", "volatility")
    assert status.strategies[1].optional_feature_groups == ("microstructure",)
    assert all(item.aggregation_weight == 1 for item in status.strategies)
    assert [item.symbol for item in status.symbols] == ["BTCUSDT", "ETHUSDT"]
    assert source.calls == ["BTCUSDT", "ETHUSDT"]


def test_bad_configuration_and_unconfigured_provider_are_explicit_errors() -> None:
    with pytest.raises(ValueError):
        StrategyEngine(symbols=("BTCUSDT", "BTCUSDT"))
    with pytest.raises(ValueError):
        StrategyEngine(symbols=("btcusdt",))
    with pytest.raises(RuntimeError):
        StrategyEngine(symbols=("BTCUSDT",)).latest("BTCUSDT")
    with pytest.raises(ValidationError):
        StrategyEngine(settings=StrategySettings().model_copy(update={"trend_weight": Decimal("NaN")}))


def test_aggregate_revalidates_copied_nonfinite_assessments() -> None:
    items = assessments((50, 50, 50))
    items = (items[0].model_copy(update={"confidence": Decimal("Infinity")}), *items[1:])
    with pytest.raises(ValueError):
        aggregate(items, StrategySettings())


def test_pure_evaluation_preserves_input_and_evidence_order_without_reading_clock() -> None:
    def forbidden_clock():
        pytest.fail("pure evaluation must use the explicit snapshot as-of time")

    snapshot = positive_momentum()
    original = snapshot.model_dump_json()
    engine = StrategyEngine(settings=StrategySettings(enabled_strategies=(StrategyId.MOMENTUM,)), clock=forbidden_clock)
    result = engine.evaluate(snapshot)
    assert snapshot.model_dump_json() == original
    assert [item.name for item in result.assessments[0].evidence] == [
        "roc_percent", "rsi_continuation", "close_change_over_vwap", "taker_buy_bias",
        "relative_volume_quality", "rsi_exhaustion_quality", "taker_base_volume_delta_proxy",
        "optional_spread_quality", "score_strength", "directional_agreement",
    ]
    assert engine.evaluate(snapshot) == result
