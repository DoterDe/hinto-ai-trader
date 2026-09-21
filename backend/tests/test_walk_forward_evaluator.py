"""Production replay integration, local identities and causal window evidence."""

import asyncio
from contextlib import aclosing
from datetime import timedelta
from decimal import localcontext

import pytest

from backtest_fixtures import START, bar, wave_bars
from src.application.backtest_engine import BacktestEngine
from src.application.backtest_metrics import calculate_metrics
from src.application.backtest_settings import BacktestSettings
from src.application.historical_dataset import validate_historical_dataset
from src.application.historical_replay import HistoricalReplay
from src.application.walk_forward import protocol_identity
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.walk_forward import WalkForwardEvaluation, WalkForwardProtocol


def dataset(rows=None, *, symbols=("BTCUSDT",), count=105, **kwargs):
    return validate_historical_dataset(list(wave_bars(count)) if rows is None else rows,
                                       symbols=symbols, **kwargs).require_dataset()


def protocol(data, **updates):
    return WalkForwardProtocol(dataset_id=data.manifest.dataset_id, symbols=data.manifest.symbols,
                               interval=data.manifest.interval, **updates)


def local_window(window):
    return window.model_dump(exclude={"split": {"dataset_id"}})


def capture_frames(monkeypatch):
    original = HistoricalReplay.frames
    runs = []

    async def recording(self, rows):
        captured = []
        runs.append(captured)
        async with aclosing(original(self, rows)) as frames:
            async for frame in frames:
                captured.append(frame)
                yield frame

    monkeypatch.setattr(HistoricalReplay, "frames", recording)
    return runs


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,rolling", [("EXPANDING", None), ("ROLLING", 50)])
async def test_repeatable_windows_use_fixed_settings_and_roundtrip_models(mode, rolling):
    data = dataset()
    engine = WalkForwardEvaluator(protocol(data, mode=mode, rolling_context_boundaries=rolling))
    data_before, protocol_before = data.model_dump_json(), engine.protocol.model_dump_json()
    settings_before = (engine.replay.feature_settings.model_dump_json(), engine.replay.strategy_settings.model_dump_json(),
                       engine.replay.decision_settings.model_dump_json(), engine.backtest_settings.model_dump_json())
    first, second = await engine.run(data), await engine.run(data)
    assert first.model_dump_json() == second.model_dump_json()
    assert WalkForwardEvaluation.model_validate_json(first.model_dump_json()) == first
    assert len(first.windows) == 3
    assert len({item.result_id for item in first.windows}) == 3
    assert all(item.engines == first.engines for item in first.windows)
    assert settings_before == (engine.replay.feature_settings.model_dump_json(), engine.replay.strategy_settings.model_dump_json(),
                               engine.replay.decision_settings.model_dump_json(), engine.backtest_settings.model_dump_json())
    assert data.model_dump_json() == data_before
    assert engine.protocol.model_dump_json() == protocol_before
    assert "NaN" not in first.model_dump_json() and "Infinity" not in first.model_dump_json()


@pytest.mark.asyncio
async def test_windows_match_existing_backtest_without_scoring_context_or_borrowing_exit_tail():
    data = dataset()
    costs = BacktestSettings(holding_period_bars=5, fee_bps_per_side=5, slippage_bps_per_side=2)
    # The cutoff straddles the fixture's known five-bar outcome horizons, so both
    # completion and censoring are exercised without changing any analytical rule.
    result = await WalkForwardEvaluator(protocol(data, test_boundaries=23, step_boundaries=23), backtest_settings=costs).run(data)
    first = result.windows[0]
    rows = tuple(row for row in data.bars if row.close_time <= first.split.test_end)
    direct = await BacktestEngine(symbols=data.manifest.symbols, settings=costs).run(rows)
    observations = tuple(item for item in direct.decisions if item.source_bar_open_time >= first.split.test_start)
    ids = {item.decision.decision_id for item in observations}
    outcomes = tuple(item for item in direct.outcomes if item.decision_id in ids)
    assert first.decisions == observations and first.outcomes == outcomes
    assert first.metrics == calculate_metrics(observations, outcomes, cutoff=first.split.test_end)
    assert len(first.decisions) == 23 and len(direct.decisions) == 73
    assert first.metrics.completed_count > 0 and first.metrics.incomplete_count > 0
    assert "INCOMPLETE_OUTCOMES" in first.warnings
    assert "BOUNDARY_CENSORED_OUTCOMES" in first.warnings
    for outcome in first.outcomes:
        if outcome.status == "COMPLETED":
            assert outcome.entry_time == outcome.decision_time
            assert outcome.exit_time == outcome.entry_time + timedelta(minutes=5)
            assert outcome.exit_time <= first.split.test_end
        else:
            assert outcome.returns is None and outcome.exit_time is None


@pytest.mark.asyncio
async def test_context_warms_actual_features_without_optional_stream_fabrication(monkeypatch):
    captured = capture_frames(monkeypatch)
    data = dataset(count=75)
    result = await WalkForwardEvaluator(protocol(data)).run(data)
    first_test = captured[0][50]
    assert first_test.features.closed_candles == 51
    for group in ("returns", "trend", "momentum", "volatility", "volume", "regime"):
        assert getattr(first_test.features, group).state == "ready"
    for group in ("trade", "microstructure", "mark_funding"):
        assert getattr(first_test.features, group).values is None
    assert result.windows[0].evidence[0].boundary == first_test.bar.close_time
    assert len(captured[0]) == 70


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,rolling", [("EXPANDING", None), ("ROLLING", 50)])
@pytest.mark.parametrize("mutation_index,unchanged_windows", [(95, 1), (120, 2)])
async def test_future_mutation_preserves_earlier_full_frames_outcomes_and_local_ids(monkeypatch, mode, rolling, mutation_index, unchanged_windows):
    captured = capture_frames(monkeypatch)
    rows = list(wave_bars(135))
    original = dataset(rows)
    changed = dataset(rows[:mutation_index] + [bar(mutation_index, opened="900", closed="901")] + rows[mutation_index + 1:])
    before_protocol = protocol(original, mode=mode, rolling_context_boundaries=rolling, test_boundaries=30, step_boundaries=30)
    after_protocol = protocol(changed, mode=mode, rolling_context_boundaries=rolling, test_boundaries=30, step_boundaries=30)
    before = await WalkForwardEvaluator(before_protocol).run(original)
    old_frames = list(captured)
    captured.clear()
    after = await WalkForwardEvaluator(after_protocol).run(changed)
    assert before.protocol.dataset_id != after.protocol.dataset_id
    assert before.evaluation_id != after.evaluation_id
    assert protocol_identity(before_protocol) == protocol_identity(after_protocol)
    assert before.windows[0].metrics.completed_count > 0  # never a vacuous outcome comparison
    for index in range(unchanged_windows):
        left, right = before.windows[index], after.windows[index]
        assert left.split.split_id == right.split.split_id
        assert left.result_id == right.result_id
        assert local_window(left) == local_window(right)
        assert old_frames[index] == captured[index]  # includes actual features, strategies and decisions
        assert left.outcomes == right.outcomes
    changed_window = unchanged_windows
    assert before.windows[changed_window].result_id != after.windows[changed_window].result_id
    assert before.windows[changed_window].evidence != after.windows[changed_window].evidence


@pytest.mark.asyncio
async def test_next_bar_cannot_change_current_features_strategy_or_decision(monkeypatch):
    captured = capture_frames(monkeypatch)
    rows = list(wave_bars(70))
    first = dataset(rows)
    second = dataset(rows[:51] + [bar(51, opened="900", closed="901")] + rows[52:])
    before = await WalkForwardEvaluator(protocol(first)).run(first)
    after = await WalkForwardEvaluator(protocol(second)).run(second)
    assert captured[0][:51] == captured[1][:51]
    assert before.windows[0].decisions[0] == after.windows[0].decisions[0]
    assert before.windows[0].evidence[0] == after.windows[0].evidence[0]
    assert captured[0][51].features != captured[1][51].features


@pytest.mark.asyncio
async def test_future_symbol_row_addition_does_not_change_earlier_windows():
    symbols = ("BTCUSDT", "ETHUSDT")
    rows = [row for pair in zip(wave_bars(100), wave_bars(100, symbol="ETHUSDT")) for row in pair]
    original = dataset([row for row in rows if not (row.symbol == "ETHUSDT" and row.open_time == START + timedelta(minutes=85))], symbols=symbols)
    added = dataset(rows, symbols=symbols)
    first = await WalkForwardEvaluator(protocol(original)).run(original)
    second = await WalkForwardEvaluator(protocol(added)).run(added)
    assert local_window(first.windows[0]) == local_window(second.windows[0])
    assert first.windows[1].result_id != second.windows[1].result_id
    assert "VALID_WITH_GAPS" in first.windows[1].warnings


@pytest.mark.asyncio
async def test_reversing_equal_time_and_full_input_order_has_identical_outputs(monkeypatch):
    captured = capture_frames(monkeypatch)
    symbols = ("BTCUSDT", "ETHUSDT")
    rows = [row for pair in zip(wave_bars(75), wave_bars(75, symbol="ETHUSDT")) for row in pair]
    first, second = dataset(rows, symbols=symbols), dataset(reversed(rows), symbols=tuple(reversed(symbols)))
    left = await WalkForwardEvaluator(protocol(first)).run(first)
    right = await WalkForwardEvaluator(protocol(second)).run(second)
    assert left.model_dump_json() == right.model_dump_json()
    assert captured[:len(left.windows)] == captured[len(left.windows):]
    assert left.windows[0].metrics.evaluated_decision_count == 40


@pytest.mark.asyncio
async def test_zero_signal_window_is_preserved_with_unchanged_thresholds():
    data = dataset([bar(i, opened="100", closed="100") for i in range(70)])
    result = await WalkForwardEvaluator(protocol(data)).run(data)
    window = result.windows[0]
    assert window.status == "EVALUATED"
    assert window.metrics.eligible_count == 0 and window.metrics.evaluated_decision_count == 20
    assert window.outcomes == () and "VALID_NO_SIGNALS" in window.warnings


@pytest.mark.asyncio
async def test_rejected_context_and_partial_windows_have_no_invented_metrics(monkeypatch):
    captured = capture_frames(monkeypatch)
    data = dataset([row for row in wave_bars(95) if row.open_time != START + timedelta(minutes=10)])
    result = await WalkForwardEvaluator(protocol(data, partial_window="REJECT")).run(data)
    assert [window.status for window in result.windows] == ["INSUFFICIENT_CONTEXT", "EVALUATED", "PARTIAL_WINDOW_REJECTED"]
    assert len(captured) == 1
    for window in (result.windows[0], result.windows[2]):
        assert window.metrics is None
        assert window.decisions == window.outcomes == window.evidence == ()


@pytest.mark.asyncio
async def test_test_gap_keeps_existing_missing_entry_and_readiness_semantics(monkeypatch):
    captured = capture_frames(monkeypatch)
    rows = list(wave_bars(80))
    base = dataset(rows)
    complete = await WalkForwardEvaluator(protocol(base)).run(base)
    eligible = next(item for item in complete.windows[0].decisions if item.decision.outcome == "ELIGIBLE")
    missing = eligible.source_bar_close_time
    data = dataset([row for row in rows if row.open_time != missing])
    captured.clear()
    result = await WalkForwardEvaluator(protocol(data)).run(data)
    window = result.windows[0]
    outcome = next(item for item in window.outcomes if item.decision_id == eligible.decision.decision_id)
    assert outcome.reason == "missing_entry_bar" and outcome.returns is None
    assert "VALID_WITH_GAPS" in window.warnings
    following = next(frame for frame in captured[0] if frame.bar.open_time > missing)
    assert following.features.last_history_reset == "candle_gap"
    assert following.features.closed_candles == 1
    assert following.features.trend.state == "warming_up"


@pytest.mark.asyncio
async def test_empty_test_range_is_explicit_evidence_not_skipped():
    data = dataset(list(wave_bars(50)), start=START, end=START + timedelta(minutes=70))
    result = await WalkForwardEvaluator(protocol(data)).run(data)
    window = result.windows[0]
    assert window.status == "EVALUATED"
    assert window.metrics.evaluated_decision_count == 0
    assert window.warnings == ("VALID_WITH_GAPS", "NO_TEST_OBSERVATIONS", "VALID_NO_SIGNALS")


@pytest.mark.asyncio
async def test_overlap_keeps_window_namespaces_without_ambiguous_duplicate_outcomes():
    data = dataset(count=80)
    result = await WalkForwardEvaluator(protocol(data, step_boundaries=10, allow_test_overlap=True)).run(data)
    for window in result.windows:
        ids = [outcome.outcome_id for outcome in window.outcomes]
        assert len(ids) == len(set(ids))
    assert len({window.result_id for window in result.windows}) == 3
    common = set(item.decision.decision_id for item in result.windows[0].decisions) & set(
        item.decision.decision_id for item in result.windows[1].decisions)
    assert common  # Intentional cohorts; there is no cross-window summation.


@pytest.mark.asyncio
async def test_short_dataset_returns_deterministic_insufficient_plan():
    data = dataset(count=20)
    first = await WalkForwardEvaluator(protocol(data)).run(data)
    second = await WalkForwardEvaluator(protocol(data)).run(data)
    assert first == second and first.windows == () and first.plan.status == "INSUFFICIENT_CONTEXT"


@pytest.mark.asyncio
async def test_ambient_precision_does_not_change_window_values_or_ids():
    data = dataset(count=75)
    engine = WalkForwardEvaluator(protocol(data))
    before = await engine.run(data)
    with localcontext() as context:
        context.prec = 4
        after = await engine.run(data)
    assert before.model_dump_json() == after.model_dump_json()


@pytest.mark.asyncio
async def test_cancellation_and_injected_replay_error_cleanup(monkeypatch):
    from src.application.market_data_hub import MarketDataHub
    original_init = MarketDataHub.__init__
    hubs = []

    def observe(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        hubs.append(self)

    monkeypatch.setattr(MarketDataHub, "__init__", observe)
    data = dataset(count=300)
    engine = WalkForwardEvaluator(protocol(data, test_boundaries=200, step_boundaries=200))
    task = asyncio.create_task(engine.run(data))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hubs and all(hub.status().subscriber_count == 0 for hub in hubs)
    from src.application.backtest_evaluator import BacktestEvaluator

    def fail(self, observation):
        raise ValueError("injected evaluation error")

    monkeypatch.setattr(BacktestEvaluator, "accept", fail)
    with pytest.raises(ValueError, match="injected evaluation error"):
        await engine.run(data)
    assert all(hub.status().subscriber_count == 0 for hub in hubs)
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "historical-feature-engine"]


@pytest.mark.asyncio
async def test_future_entry_price_can_change_outcome_but_not_the_eligible_decision(monkeypatch):
    captured = capture_frames(monkeypatch)
    rows = list(wave_bars(80))
    original = dataset(rows)
    selected = protocol(original, test_boundaries=30, step_boundaries=30)
    first = await WalkForwardEvaluator(selected).run(original)
    outcome = next(item for item in first.windows[0].outcomes if item.status == "COMPLETED")
    entry_index = int((outcome.entry_time - START).total_seconds()) // 60
    changed = dataset(rows[:entry_index] + [bar(entry_index, opened="900", closed="901")] + rows[entry_index + 1:])
    second = await WalkForwardEvaluator(selected.model_copy(update={"dataset_id": changed.manifest.dataset_id})).run(changed)
    later = next(item for item in second.windows[0].outcomes if item.decision_id == outcome.decision_id)
    assert captured[0][:entry_index] == captured[1][:entry_index]
    before_decision = next(item for item in first.windows[0].decisions if item.decision.decision_id == outcome.decision_id)
    after_decision = next(item for item in second.windows[0].decisions if item.decision.decision_id == outcome.decision_id)
    assert before_decision == after_decision
    assert later.status == "COMPLETED"
    assert outcome.entry_price_raw != later.entry_price_raw
    assert outcome.returns != later.returns and outcome.outcome_id != later.outcome_id


@pytest.mark.asyncio
async def test_rolling_window_matches_independent_replay_of_only_its_own_context(monkeypatch):
    captured = capture_frames(monkeypatch)
    data = dataset(count=100)
    result = await WalkForwardEvaluator(protocol(data, mode="ROLLING", rolling_context_boundaries=50)).run(data)
    window = result.windows[1]
    assert all(run[0].features.closed_candles == 1 for run in captured)
    assert captured[1][0].bar.open_time == window.split.context_start
    rows = tuple(row for row in data.bars if window.split.context_start <= row.open_time < window.split.test_end)
    direct = await BacktestEngine(symbols=data.manifest.symbols).run(rows)
    decisions = tuple(item for item in direct.decisions if item.source_bar_open_time >= window.split.test_start)
    ids = {item.decision.decision_id for item in decisions}
    outcomes = tuple(item for item in direct.outcomes if item.decision_id in ids)
    assert window.decisions == decisions and window.outcomes == outcomes
    assert window.metrics == calculate_metrics(decisions, outcomes, cutoff=window.split.test_end)
