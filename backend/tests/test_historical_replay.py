import asyncio
from contextlib import aclosing
from datetime import timedelta
from decimal import Decimal

import pytest

from backtest_fixtures import START, bar, wave_bars
from src.application.decision_engine import DecisionEngine
from src.application.historical_replay import DecisionCapture, HistoricalReplay, ReplayClock
from src.application.strategy_engine import StrategyEngine
from src.domain.backtesting import HistoricalDecision


async def collect(bars, symbols=("BTCUSDT",)):
    return [frame async for frame in HistoricalReplay(symbols=symbols).frames(bars)]


def test_replay_clock_is_explicit_monotonic_and_has_no_wall_clock():
    clock = ReplayClock(START)
    clock.advance(START)
    clock.advance(START + timedelta(days=1))
    assert clock() == START + timedelta(days=1)
    for invalid in (START, START.replace(tzinfo=None), 1):
        with pytest.raises(ValueError):
            clock.advance(invalid)


@pytest.mark.asyncio
async def test_actual_pipeline_is_repeatable_with_production_warmup_and_eligibility():
    first, second = await collect(wave_bars()), await collect(wave_bars())
    assert len(first) == len(second) == 80
    assert [frame.features.model_dump_json() for frame in first] == [frame.features.model_dump_json() for frame in second]
    assert [frame.strategy.model_dump_json() for frame in first] == [frame.strategy.model_dump_json() for frame in second]
    assert [frame.observation.model_dump_json() for frame in first] == [frame.observation.model_dump_json() for frame in second]
    assert all(frame.features.trend.state == "warming_up" for frame in first[:49])
    assert first[49].features.trend.state == "ready"
    assert first[0].features.closed_candles == 1
    assert all(frame.observation.decision.outcome == "NO_ACTION" for frame in first[:20])
    eligible = [frame for frame in first if frame.observation.decision.outcome == "ELIGIBLE"]
    assert eligible
    for frame in eligible:
        assert abs(frame.strategy.composite_score) >= 40 and frame.strategy.confidence >= Decimal(".55")
        assert len(frame.observation.decision.contributing_strategies) >= 2
    assert all(frame.features.microstructure.values is None for frame in first)
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]


@pytest.mark.asyncio
async def test_historical_time_is_fresh_and_later_evaluation_stays_stale():
    frames = await collect(wave_bars())
    frame = next(item for item in frames if item.observation.decision.outcome == "ELIGIBLE")
    assert frame.features.generated_at == frame.bar.close_time == frame.observation.decision.generated_at
    old_strategy = StrategyEngine().evaluate(frame.features, now=frame.bar.close_time + timedelta(days=1))
    assert old_strategy.readiness == "stale"
    expired = DecisionEngine().evaluate(frame.strategy, now=frame.bar.close_time + timedelta(seconds=10))
    assert expired.outcome == "BLOCKED" and expired.readiness == "stale"


@pytest.mark.asyncio
async def test_future_bar_changes_cannot_change_prior_analytical_results():
    bars = list(wave_bars())
    changed = list(bars)
    changed[60] = bar(60, opened="900", closed="901")
    original, modified = await collect(bars), await collect(changed)
    assert [frame.observation for frame in original[:60]] == [frame.observation for frame in modified[:60]]
    assert original[60].features != modified[60].features
    for frame in original:
        assert frame.features.closed_candle_time == frame.bar.close_time
        assert frame.features.returns.values is None or frame.features.returns.values.close == frame.bar.close


@pytest.mark.asyncio
async def test_input_read_ahead_is_never_published_before_current_decision(monkeypatch):
    published = []
    from src.application.market_data_hub import MarketDataHub
    original = MarketDataHub.publish
    def observe(self, event, **kwargs):
        published.append(event.open_time)
        return original(self, event, **kwargs)
    monkeypatch.setattr(MarketDataHub, "publish", observe)
    async with aclosing(HistoricalReplay(symbols=("BTCUSDT",)).frames(wave_bars(4))) as replay:
        first = await anext(replay)
        assert published == [START]
        assert first.features.closed_candles == 1
        second = await anext(replay)
        assert published == [START, START + timedelta(minutes=1)]
        assert second.features.closed_candles == 2
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]


@pytest.mark.asyncio
async def test_multi_symbol_order_and_isolation_are_deterministic():
    bars = [event for index in range(3) for event in (bar(index, symbol="ETHUSDT", closed="150"), bar(index))]
    first = await collect(bars, ("ETHUSDT", "BTCUSDT"))
    second = await collect([event for index in range(3) for event in reversed(bars[2*index:2*index+2])], ("BTCUSDT", "ETHUSDT"))
    assert [frame.observation for frame in first] == [frame.observation for frame in second]
    assert [frame.bar.symbol for frame in first] == ["BTCUSDT", "ETHUSDT"] * 3
    assert [frame.features.closed_candles for frame in first] == [1, 1, 2, 2, 3, 3]


@pytest.mark.asyncio
async def test_gaps_are_not_filled_and_existing_history_rewarms():
    frames = await collect([bar(0), bar(1), bar(4)])
    assert len(frames) == 3
    assert frames[-1].features.closed_candles == 1
    assert frames[-1].features.last_history_reset == "candle_gap"
    assert frames[-1].features.trend.state == "warming_up"


@pytest.mark.asyncio
async def test_duplicate_capture_ignores_read_time_but_rejects_conflicting_identity():
    observation = (await collect(wave_bars(1)))[0].observation
    capture = DecisionCapture()
    assert capture.add(observation)
    later = observation.model_copy(update={"decision": observation.decision.model_copy(update={
        "generated_at": observation.decision.generated_at + timedelta(microseconds=1)})})
    assert not capture.add(later) and capture.duplicate_reads == 1
    conflict = observation.model_copy(update={"decision": observation.decision.model_copy(update={"observation_id": "changed"})})
    with pytest.raises(ValueError, match="conflicting"):
        capture.add(conflict)
    invalid = observation.model_copy(update={"decision": observation.decision.model_copy(update={"confidence": Decimal("NaN")})})
    with pytest.raises(ValueError):
        capture.add(invalid)


@pytest.mark.asyncio
async def test_dedupe_distinguishes_changed_observation():
    frames = await collect(wave_bars(3))
    capture = DecisionCapture()
    assert all(capture.add(frame.observation) for frame in frames)
    assert capture.duplicate_reads == 0


@pytest.mark.asyncio
async def test_malformed_input_and_early_close_leave_no_feature_task():
    with pytest.raises(ValueError):
        await collect([bar(), bar(1), bar(2).model_copy(update={"high": 0})])
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]
    assert await collect([]) == []


def test_historical_decision_cannot_precede_its_source():
    from test_decision_contracts import record
    with pytest.raises(ValueError):
        HistoricalDecision(source_bar_open_time=record().generated_at,
            source_bar_close_time=record().generated_at + timedelta(minutes=1), decision=record())
