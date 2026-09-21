"""Canonical evidence invariants, independent of analytical profitability."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from itertools import permutations, repeat

import pytest

from src.application.backtest_identity import DatasetIdentity
from src.application.historical_dataset import validate_historical_dataset, verify_historical_dataset
from src.application.historical_dataset_codec import HistoricalDatasetCodec
from src.domain.historical_dataset import HistoricalDataset
from backtest_fixtures import START, bar


def validate(rows, **kwargs):
    return validate_historical_dataset(rows, **({"symbols": ("BTCUSDT",)} | kwargs))


def dataset(rows, **kwargs):
    return validate(rows, **kwargs).require_dataset()


def test_identity_and_manifest_repeat_exactly():
    first = dataset([bar(), bar(1)])
    assert first == dataset(iter([bar(), bar(1)]))
    assert HistoricalDatasetCodec.encode(first) == HistoricalDatasetCodec.encode(dataset([bar(), bar(1)]))
    content = DatasetIdentity()
    for row in first.bars:
        content.add(row)
    assert first.manifest.replay_dataset_id == content.value
    assert first.manifest.content_checksum == content.value.removeprefix("dataset_")
    assert verify_historical_dataset(first) == first


def test_v1_identity_and_canonical_codec_golden_digest():
    import hashlib
    actual = dataset([bar(), bar(1)])
    assert actual.manifest.dataset_id == "historical_dataset_d20a95789e2f878bc14ea4822da034102b6edfa6682e0bcb6d6c085d4b2c9d47"
    assert hashlib.sha256(HistoricalDatasetCodec.encode(actual)).hexdigest() == "a0ad37102522b445a7617de5f3bbba0504fe699c57b1a3e504c4c17e23ec39d7"


def test_equivalent_decimal_duplicate_permutations_have_identical_model_json():
    rows = [bar(), bar(open=Decimal("100.000"), volume=Decimal("10.00")), bar(1)]
    expected = dataset(rows).model_dump_json()
    for permutation in permutations(rows):
        assert dataset(permutation).model_dump_json() == expected


def test_all_input_permutations_have_equal_time_symbol_order_and_same_identity():
    rows = [bar(), bar(symbol="ETHUSDT"), bar(1), bar(1, symbol="ETHUSDT")]
    expected = dataset(rows, symbols=("ETHUSDT", "BTCUSDT"))
    for permutation in permutations(rows):
        actual = dataset(permutation, symbols=("BTCUSDT", "ETHUSDT"))
        assert actual == expected
    assert [(row.event_time, row.symbol) for row in expected.bars] == sorted(
        (row.event_time, row.symbol) for row in rows)


@pytest.mark.parametrize("field,value", [
    ("open", "100.01"), ("high", "102"), ("low", "99"), ("close", "100.9"),
    ("volume", "11"), ("quote_volume", "1100"), ("taker_buy_volume", "7"),
    ("taker_buy_quote_volume", "700"), ("trade_count", 2),
])
def test_each_relevant_market_field_changes_identity(field, value):
    changed = bar().model_copy(update={field: value if field == "trade_count" else Decimal(value)})
    assert dataset([changed]).manifest.dataset_id != dataset([bar()]).manifest.dataset_id


def test_timestamp_interval_and_symbol_changes_change_identity():
    original = dataset([bar()]).manifest.dataset_id
    assert dataset([bar(1)]).manifest.dataset_id != original
    assert dataset([bar(symbol="ETHUSDT")], symbols=("ETHUSDT",)).manifest.dataset_id != original
    other = bar(interval="60s")
    assert dataset([other], interval="60s").manifest.dataset_id != original


def test_scope_boundaries_change_identity_but_provenance_label_does_not(tmp_path, monkeypatch):
    original = dataset([bar()])
    monkeypatch.chdir(tmp_path)
    renamed = dataset([bar()], source_label="another-public-source")
    assert renamed.manifest.dataset_id == original.manifest.dataset_id
    assert dataset([bar()], symbols=("BTCUSDT", "ETHUSDT")).manifest.dataset_id != original.manifest.dataset_id
    extended = dataset([bar()], start=START, end=START + timedelta(minutes=2))
    assert extended.manifest.dataset_id != original.manifest.dataset_id
    assert extended.manifest.content_checksum == original.manifest.content_checksum
    assert str(tmp_path).encode() not in HistoricalDatasetCodec.encode(renamed)


def test_identical_duplicates_diagnosed_once_and_never_replayed_twice():
    result = validate([bar(1), bar(), bar(), bar()])
    actual = result.require_dataset()
    assert len(result.issues) == 1
    assert result.issues[0].code == "identical_duplicate"
    assert result.issues[0].count == 2
    assert actual.manifest.duplicate_count == 2
    assert actual.manifest.input_bar_count == 4
    assert actual.manifest.total_bars == 2
    assert actual.manifest.conflict_count == 0
    assert actual.manifest.dataset_id == dataset([bar(), bar(1)]).manifest.dataset_id
    assert len(actual.bars) == 2
    assert HistoricalDatasetCodec.decode(HistoricalDatasetCodec.encode(actual)) == actual


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_conflicting_duplicates_fail_closed_regardless_of_input_order(order):
    rows = [bar(), bar(1), bar(volume=Decimal(11))]
    result = validate([rows[index] for index in order])
    assert result.status == "INVALID" and result.dataset is None
    assert result.issues[0].code == "conflicting_duplicate"
    assert result.issues[0].symbol == "BTCUSDT"
    assert result.issues[0].open_time == START
    with pytest.raises(ValueError, match="conflicting_duplicate"):
        result.require_dataset()


def test_canonical_contract_rejects_duplicate_or_reversed_rows():
    original = dataset([bar(), bar(1)])
    for rows in ((bar(), bar()), (bar(1), bar())):
        with pytest.raises(ValueError, match="ordered and unique"):
            HistoricalDataset.model_validate(original.model_copy(update={"bars": rows}))


def test_end_minus_one_millisecond_normalizes_to_existing_replay_convention():
    inclusive = bar(close_time=bar().close_time - timedelta(milliseconds=1))
    result = validate([inclusive, bar()])
    assert result.require_dataset().bars == (bar(),)
    assert result.issues[0].code == "identical_duplicate"


@pytest.mark.parametrize("scope", [(), ("BTCUSDT", "BTCUSDT"), ("btcusdt",), ("../x",), "BTCUSDT", None])
def test_invalid_scope(scope):
    assert validate([bar()], symbols=scope).status == "INVALID"


@pytest.mark.parametrize("interval", ["", "0m", "-1m", "1y", "1.5m", "99999999999999999999999w"])
def test_invalid_interval(interval):
    assert validate([bar()], interval=interval).status == "INVALID"


@pytest.mark.parametrize("row", [bar(symbol="ETHUSDT"), bar(interval="60s")])
def test_rows_must_match_declared_scope(row):
    assert validate([row]).issues[0].code == "scope_mismatch"


def test_empty_data_is_invalid():
    assert validate([]).issues[0].code == "empty_dataset"


@pytest.mark.parametrize("field,value", [
    ("is_closed", False), ("is_closed", 1), ("low", Decimal(102)), ("high", Decimal(99)),
    ("open", Decimal(0)), ("close", Decimal(-1)), ("volume", Decimal(-1)),
    ("quote_volume", Decimal(-1)), ("taker_buy_volume", Decimal(11)),
    ("taker_buy_quote_volume", Decimal(1100)), ("trade_count", -1), ("trade_count", True),
    ("open", Decimal("NaN")), ("high", Decimal("Infinity")), ("volume", Decimal("-Infinity")),
    ("event_time", START), ("received_at", START), ("close_time", START + timedelta(seconds=59)),
])
def test_invalid_bar_values_never_expose_dataset(field, value):
    result = validate([bar().model_copy(update={field: value})])
    assert result.status == "INVALID" and result.dataset is None


def test_volume_zero_with_nonzero_quote_is_invalid():
    assert validate([bar(volume=0, taker_buy_volume=0)]).status == "INVALID"


@pytest.mark.parametrize("field", ["open_time", "close_time", "event_time", "received_at"])
@pytest.mark.parametrize("bad_time", [START.replace(tzinfo=None), START.astimezone(timezone(timedelta(hours=5))), "2020-01-01", None])
def test_all_timestamps_require_aware_utc_datetimes(field, bad_time):
    assert validate([bar().model_copy(update={field: bad_time})]).status == "INVALID"


def test_unaligned_grid_rejected_even_with_consistent_bar_duration():
    row = bar()
    shifted = row.model_copy(update={field: getattr(row, field) + timedelta(seconds=1)
        for field in ("open_time", "close_time", "event_time", "received_at")})
    assert validate([shifted]).status == "INVALID"


@pytest.mark.parametrize("bounds", [
    {"start": START}, {"end": START}, {"start": START, "end": START},
    {"start": START, "end": START - timedelta(minutes=1)},
    {"start": START.replace(tzinfo=None), "end": START + timedelta(minutes=1)},
    {"start": START, "end": START + timedelta(seconds=61)},
    {"start": START + timedelta(minutes=1), "end": START + timedelta(minutes=2)},
])
def test_declared_boundaries_fail_closed(bounds):
    assert validate([bar()], **bounds).issues[0].code == "invalid_bounds"


def test_future_or_past_rows_outside_bounds_are_rejected_not_trimmed():
    for rows in ([bar(), bar(2)], [bar(0), bar(1)]):
        assert validate(rows, start=START + timedelta(minutes=1), end=START + timedelta(minutes=2)).status == "INVALID"


def test_per_symbol_leading_internal_trailing_and_absent_coverage_no_fill():
    rows = [bar(1), bar(3), bar(2, symbol="ETHUSDT")]
    actual = dataset(rows, symbols=("SOLUSDT", "ETHUSDT", "BTCUSDT"), start=START, end=START + timedelta(minutes=5))
    manifest = actual.manifest
    assert manifest.status == "VALID_WITH_GAPS"
    assert manifest.total_bars == 3 and len(actual.bars) == 3
    btc, eth, sol = manifest.coverage
    assert [item.observed_bars for item in manifest.coverage] == [2, 1, 0]
    assert [item.missing_bars for item in manifest.coverage] == [3, 4, 5]
    assert [item.coverage_fraction for item in manifest.coverage] == [Decimal(".4"), Decimal(".2"), 0]
    assert len(btc.gaps) == 3 and len(eth.gaps) == 2 and len(sol.gaps) == 1
    assert sol.first_open is None and sol.last_boundary is None
    assert manifest.gap_count == 6 and manifest.missing_bar_count == 12
    assert btc.gaps[1].start == START + timedelta(minutes=2)
    assert btc.gaps[1].end == START + timedelta(minutes=3)
    assert manifest.first_open == START + timedelta(minutes=1)
    assert manifest.first_boundary == START + timedelta(minutes=2)
    assert manifest.last_boundary == START + timedelta(minutes=4)


def test_calendar_month_gaps_use_months_not_assumed_days():
    def monthly(month):
        opened, end = datetime(2020, month, 1, tzinfo=timezone.utc), datetime(2020, month + 1, 1, tzinfo=timezone.utc)
        return bar(interval="1M", open_time=opened, close_time=end, event_time=end, received_at=end)
    actual = dataset([monthly(1), monthly(3)], interval="1M")
    gap = actual.manifest.coverage[0].gaps[0]
    assert gap.start == datetime(2020, 2, 1, tzinfo=timezone.utc)
    assert gap.end == datetime(2020, 3, 1, tzinfo=timezone.utc)
    assert gap.missing_bars == 1
    assert actual.manifest.coverage[0].expected_bars == 3


def test_large_missing_range_is_one_diagnostic_not_materialized_rows():
    end = datetime(9999, 1, 1, tzinfo=timezone.utc)
    actual = dataset([bar()], start=START, end=end)
    assert len(actual.bars) == 1
    assert len(actual.manifest.coverage[0].gaps) == 1
    assert actual.manifest.missing_bar_count == int((end - START).total_seconds()) // 60 - 1


def test_decimal_precision_scale_zero_and_context_do_not_change_identity_or_bytes():
    value = Decimal("100.123456789012345678901234567890123456789")
    row = bar(open=value)
    expected = dataset([row, bar(2)])
    with localcontext() as context:
        context.prec = 3
        actual = dataset([row, bar(2)])
        encoded = HistoricalDatasetCodec.encode(actual)
        decoded = HistoricalDatasetCodec.decode(encoded)
    assert actual == expected == decoded
    assert decoded.bars[0].open == value
    scaled = bar(open=Decimal("100.000"), volume=Decimal("10.00"), taker_buy_volume=Decimal("8.000"))
    assert HistoricalDatasetCodec.encode(dataset([scaled])) == HistoricalDatasetCodec.encode(dataset([bar()]))
    zero = bar(taker_buy_volume=Decimal("-0.000"))
    assert HistoricalDatasetCodec.encode(dataset([zero])) == HistoricalDatasetCodec.encode(dataset([bar(taker_buy_volume=0)]))


@pytest.mark.parametrize("field,value", [("volume", Decimal("1e1001")), ("volume", Decimal("1" * 129)),
                                          ("trade_count", 2**63)])
def test_numeric_resource_limits(field, value):
    assert validate([bar().model_copy(update={field: value})]).issues[0].code == "limit_exceeded"


def test_input_budget_counts_duplicates_and_stops_infinite_iterators(monkeypatch):
    import src.application.historical_dataset as module
    monkeypatch.setattr(module, "MAX_INPUT_BARS", 3)
    assert validate(repeat(bar())).issues[0].code == "limit_exceeded"
    assert validate([bar(), bar(), bar()]).status == "VALID"


def test_symbol_budget(monkeypatch):
    import src.application.historical_dataset as module
    monkeypatch.setattr(module, "MAX_SYMBOLS", 1)
    assert validate([bar()], symbols=("BTCUSDT", "ETHUSDT")).issues[0].code == "invalid_scope"


@pytest.mark.parametrize("label", ["", "/tmp/data", "C:\\data", "https://public.example", "x" * 65])
def test_source_label_is_bounded_metadata_not_a_host_path(label):
    assert validate([bar()], source_label=label).status == "INVALID"


@pytest.mark.parametrize("value", [Decimal("1000e-1003"), Decimal("1" + "0" * 128), Decimal("1e1000")])
def test_numeric_limits_apply_to_canonical_value_not_decimal_scale(value):
    actual = dataset([bar(volume=value, taker_buy_volume=0)])
    assert HistoricalDatasetCodec.decode(HistoricalDatasetCodec.encode(actual)) == actual


def test_canonical_exponent_outside_limit_is_rejected_before_export():
    result = validate([bar(volume=Decimal("1000e1000"))])
    assert result.issues[0].code == "limit_exceeded"
