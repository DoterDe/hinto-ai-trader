"""Boundary math and explicit evidence admission, without strategy fitting."""

from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest

from backtest_fixtures import START, bar
from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.historical_dataset import validate_historical_dataset
from src.application.market_data_hub import MarketDataHub
from src.application.walk_forward import build_walk_forward_plan, protocol_identity, required_warmup
from src.domain.walk_forward import WalkForwardProtocol


def dataset(count=105, *, symbols=("BTCUSDT",), missing=()):
    rows = [bar(i, symbol=symbol) for i in range(count) for symbol in symbols if (i, symbol) not in missing]
    return validate_historical_dataset(rows, symbols=symbols, start=START, end=START + timedelta(minutes=count)).require_dataset()


def protocol(data, **kwargs):
    return WalkForwardProtocol(dataset_id=data.manifest.dataset_id, symbols=data.manifest.symbols,
                               interval=data.manifest.interval, **kwargs)


@pytest.mark.parametrize("mode,rolling,expected", [
    ("EXPANDING", None, [(0, 50, 70), (0, 70, 90), (0, 90, 105)]),
    ("ROLLING", 50, [(0, 50, 70), (20, 70, 90), (40, 90, 105)]),
    ("ROLLING", 60, [(0, 60, 80), (20, 80, 100), (40, 100, 105)]),
])
def test_exact_expanding_and_rolling_ranges(mode, rolling, expected):
    data = dataset()
    selected = protocol(data, mode=mode, rolling_context_boundaries=rolling)
    plan = build_walk_forward_plan(data, selected)
    assert plan.status == "READY"
    assert [(int((split.context_start - START).total_seconds() / 60),
             int((split.test_start - START).total_seconds() / 60),
             int((split.test_end - START).total_seconds() / 60)) for split in plan.splits] == expected
    for ordinal, split in enumerate(plan.splits):
        assert split.ordinal == ordinal and split.context_end == split.test_start
        assert split.required_warmup == 50
        assert split.status == "READY"
        assert split.context_coverage[0].observed_bars == split.context_boundary_count
        assert split.test_coverage[0].observed_bars == split.test_boundary_count
        if ordinal:
            assert plan.splits[ordinal - 1].test_end == split.test_start
    assert plan.splits[-1].warnings == ("PARTIAL_TEST_WINDOW",)


@pytest.mark.parametrize("field", ["minimum_context_boundaries", "warmup_boundaries", "test_boundaries", "step_boundaries", "rolling_context_boundaries"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "20", 100001])
def test_sizes_are_strict_positive_bounded_counts(field, value):
    with pytest.raises(ValueError):
        protocol(dataset(2), **{field: value})


@pytest.mark.parametrize("updates", [
    {"mode": "UNKNOWN"}, {"mode": "ROLLING"}, {"mode": "ROLLING", "rolling_context_boundaries": 49},
    {"rolling_context_boundaries": 50}, {"minimum_context_boundaries": 49},
    {"warmup_boundaries": 51}, {"step_boundaries": 10}, {"allow_test_overlap": True},
    {"allow_test_overlap": 1}, {"partial_window": "DROP"}, {"version": "walk-forward-v2"},
    {"dataset_schema_version": "unknown"},
])
def test_invalid_protocol_combinations(updates):
    with pytest.raises(ValueError):
        protocol(dataset(2), **updates)


def test_overlap_requires_opt_in_and_is_part_of_identity():
    data = dataset(90)
    selected = protocol(data, step_boundaries=10, allow_test_overlap=True)
    plan = build_walk_forward_plan(data, selected)
    assert plan.splits[0].test_end > plan.splits[1].test_start
    assert "OVERLAPPING_TEST_WINDOWS" in plan.splits[0].warnings
    assert len({split.split_id for split in plan.splits}) == len(plan.splits)
    assert protocol_identity(selected) != protocol_identity(protocol(data))


def test_steps_larger_than_test_are_explicit_not_silent():
    data = dataset(100)
    plan = build_walk_forward_plan(data, protocol(data, step_boundaries=30))
    assert plan.splits[1].test_start - plan.splits[0].test_end == timedelta(minutes=10)
    assert "SKIPPED_TEST_BOUNDARIES" in plan.splits[0].warnings


def test_partial_window_rejection_keeps_split_in_plan():
    data = dataset()
    plan = build_walk_forward_plan(data, protocol(data, partial_window="REJECT"))
    assert len(plan.splits) == 3
    assert plan.splits[-1].status == "PARTIAL_WINDOW_REJECTED"
    assert plan.splits[-1].test_boundary_count == 15


@pytest.mark.parametrize("count,status", [(49, "INSUFFICIENT_CONTEXT"), (50, "NO_TEST_BOUNDARIES")])
def test_no_test_window_is_explained(count, status):
    data = dataset(count)
    plan = build_walk_forward_plan(data, protocol(data))
    assert plan.status == status and plan.splits == ()


def test_symbols_are_canonical_and_unique():
    key = dataset(2).manifest.dataset_id
    first = WalkForwardProtocol(dataset_id=key, symbols=("ETHUSDT", "BTCUSDT"))
    second = WalkForwardProtocol(dataset_id=key, symbols=("BTCUSDT", "ETHUSDT"))
    assert first == second and protocol_identity(first) == protocol_identity(second)
    for symbols in ((), ("BTCUSDT", "BTCUSDT"), ("../bad",), "BTCUSDT"):
        with pytest.raises(ValueError):
            WalkForwardProtocol(dataset_id=key, symbols=symbols)


@pytest.mark.parametrize("field,value", [("dataset_id", "historical_dataset_" + "0" * 64), ("symbols", ("ETHUSDT",)), ("interval", "60s")])
def test_plan_rejects_mismatched_dataset(field, value):
    data = dataset()
    with pytest.raises(ValueError, match="identity and scope"):
        build_walk_forward_plan(data, protocol(data).model_copy(update={field: value}))


@pytest.mark.parametrize("settings", [FeatureSettings(), FeatureSettings(ema_long=60), FeatureSettings(rsi_period=70),
    FeatureSettings(atr_period=65), FeatureSettings(roc_period=65), FeatureSettings(volatility_window=80),
    FeatureSettings(relative_volume_window=70), FeatureSettings(vwap_window=100), FeatureSettings(rolling_return_windows=(5, 90))])
def test_warmup_matches_actual_feature_engine_public_sample_requirements(settings):
    engine = FeatureEngine(MarketDataHub(("BTCUSDT",), clock=lambda: START), settings)
    groups = engine.status().symbols[0].groups
    assert required_warmup(settings) == max(group.required_samples for group in groups
                                           if group.name not in ("trade", "microstructure", "mark_funding"))
    data = dataset(105)
    needed = required_warmup(settings)
    if needed > 50:
        with pytest.raises(ValueError, match="feature requirement"):
            build_walk_forward_plan(data, protocol(data), feature_settings=settings)
    plan = build_walk_forward_plan(data, protocol(data, minimum_context_boundaries=needed,
                                   warmup_boundaries=needed), feature_settings=settings)
    assert plan.required_warmup == needed


def test_missing_context_per_symbol_rejects_split_without_borrowing_test_rows():
    data = dataset(105, symbols=("BTCUSDT", "ETHUSDT"), missing=((10, "ETHUSDT"),))
    plan = build_walk_forward_plan(data, protocol(data))
    first = plan.splits[0]
    assert first.status == "INSUFFICIENT_CONTEXT"
    assert first.insufficient_context_symbols == ("ETHUSDT",)
    assert first.context_coverage[1].missing_bars == 1
    assert plan.splits[1].status == "READY"  # 59 contiguous past ETH bars now exist.
    assert "VALID_WITH_GAPS" in plan.splits[1].warnings


def test_missing_entire_boundary_is_an_empty_slot_not_a_fabricated_group():
    data = dataset(75, symbols=("BTCUSDT", "ETHUSDT"), missing=((55, "ETHUSDT"), (55, "BTCUSDT"), (60, "ETHUSDT")))
    split = build_walk_forward_plan(data, protocol(data)).splits[0]
    assert split.test_boundary_count == 20 and split.observed_test_boundaries == 19
    assert [coverage.missing_bars for coverage in split.test_coverage] == [1, 2]
    assert [coverage.observed_bars for coverage in split.test_coverage] == [19, 18]
    assert split.status == "READY" and "VALID_WITH_GAPS" in split.warnings


def test_absent_symbol_remains_explicit():
    data = validate_historical_dataset([bar(i) for i in range(75)], symbols=("BTCUSDT", "ETHUSDT")).require_dataset()
    split = build_walk_forward_plan(data, protocol(data)).splits[0]
    assert split.status == "INSUFFICIENT_CONTEXT"
    assert split.insufficient_context_symbols == ("ETHUSDT",)
    assert split.context_coverage[1].observed_bars == split.test_coverage[1].observed_bars == 0


def test_same_time_symbols_never_split_and_source_order_does_not_matter():
    data = dataset(75, symbols=("BTCUSDT", "ETHUSDT"))
    for symbols in permutations(data.manifest.symbols):
        reordered = validate_historical_dataset(reversed(data.bars), symbols=symbols).require_dataset()
        assert build_walk_forward_plan(reordered, protocol(reordered)) == build_walk_forward_plan(data, protocol(data))
    first = build_walk_forward_plan(data, protocol(data)).splits[0]
    assert first.test_boundary_count == 20
    assert sum(item.observed_bars for item in first.test_coverage) == 40


def test_calendar_month_boundaries_have_no_fixed_day_assumption():
    rows = []
    for index in range(75):
        opened = datetime(2020 + index // 12, index % 12 + 1, 1, tzinfo=timezone.utc)
        end = datetime(2020 + (index + 1) // 12, (index + 1) % 12 + 1, 1, tzinfo=timezone.utc)
        rows.append(bar(interval="1M", open_time=opened, close_time=end, event_time=end, received_at=end))
    data = validate_historical_dataset(rows, symbols=("BTCUSDT",), interval="1M").require_dataset()
    split = build_walk_forward_plan(data, protocol(data)).splits[0]
    assert split.context_start == START
    assert split.test_start == datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert split.test_end == datetime(2025, 11, 1, tzinfo=timezone.utc)


def test_resource_limits_fail_before_replay_or_expanding_huge_missing_ranges(monkeypatch):
    import src.application.walk_forward as module
    data = dataset()
    monkeypatch.setattr(module, "MAX_SPLITS", 1)
    with pytest.raises(ValueError, match="split budget"):
        build_walk_forward_plan(data, protocol(data))
    monkeypatch.setattr(module, "MAX_SPLITS", 256)
    monkeypatch.setattr(module, "MAX_REPLAY_ROWS", 100)
    with pytest.raises(ValueError, match="replay/evidence budget"):
        build_walk_forward_plan(data, protocol(data))


def test_sparse_expanding_context_counts_slots_separately_from_input_row_limit():
    data = validate_historical_dataset([bar()], symbols=("BTCUSDT",), start=START,
                                      end=START + timedelta(minutes=100100)).require_dataset()
    selected = protocol(data, test_boundaries=100000, step_boundaries=100000)
    plan = build_walk_forward_plan(data, selected)
    assert len(plan.splits) == 2
    assert plan.splits[1].context_boundary_count == 100050
    assert plan.splits[1].observed_context_boundaries == 1
    assert all(split.status == "INSUFFICIENT_CONTEXT" for split in plan.splits)
