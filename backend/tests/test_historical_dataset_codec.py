"""Strict export/import with derived-manifest and content verification."""

import json
from decimal import Decimal

import pytest

from src.application.historical_dataset import validate_historical_dataset
from src.application.historical_dataset_codec import HistoricalDatasetCodec as Codec
from backtest_fixtures import bar


def evidence():
    return validate_historical_dataset([bar(), bar(2), bar()], symbols=("BTCUSDT", "ETHUSDT")).require_dataset()


def document():
    return json.loads(Codec.encode(evidence()))


def test_export_is_canonical_json_with_exact_values_and_roundtrip_bytes():
    payload = Codec.encode(evidence())
    raw = json.loads(payload)
    assert payload == (json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert raw["bars"][0]["open"] == "1e2"
    assert raw["bars"][0]["open_time"].endswith("Z")
    assert Codec.encode(Codec.decode(payload)) == payload
    # Insignificant JSON layout need not already be canonical on import.
    assert Codec.decode(json.dumps(raw, indent=2).encode()) == evidence()


@pytest.mark.parametrize("section", ["root", "manifest", "bar", "coverage", "gap", "duplicate"])
def test_unknown_fields_rejected(section):
    raw = document()
    node = {"root": raw, "manifest": raw["manifest"], "bar": raw["bars"][0],
            "coverage": raw["manifest"]["coverage"][0], "gap": raw["manifest"]["coverage"][0]["gaps"][0],
            "duplicate": raw["manifest"]["duplicates"][0]}[section]
    node["unexpected"] = 1
    with pytest.raises(ValueError):
        Codec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize("field,value", [
    ("schema_version", "historical-dataset-v2"), ("dataset_id", "historical_dataset_" + "0" * 64),
    ("content_checksum", "0" * 64), ("replay_dataset_id", "dataset_" + "0" * 64),
    ("total_bars", 3), ("input_bar_count", 999), ("duplicate_count", 7), ("conflict_count", 1),
    ("gap_count", 0), ("missing_bar_count", 0), ("status", "VALID"), ("symbols", ["BTCUSDT"]),
    ("start", "2020-01-01T00:01:00Z"), ("end", "2020-01-01T00:02:00Z"),
    ("first_open", "2019-12-31T23:59:00Z"), ("last_boundary", "2020-01-01T00:02:00Z"),
])
def test_tampered_manifest_rejected(field, value):
    raw = document()
    raw["manifest"][field] = value
    with pytest.raises(ValueError):
        Codec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize("mutation", ["price", "duplicates", "reverse", "duplicate_provenance", "gap", "ratio"])
def test_tampered_rows_or_diagnostics_rejected(mutation):
    raw = document()
    if mutation == "price":
        raw["bars"][0]["open"] = "100.01"
    elif mutation == "duplicates":
        raw["bars"][1] = raw["bars"][0]
    elif mutation == "reverse":
        raw["bars"].reverse()
    elif mutation == "duplicate_provenance":
        raw["manifest"]["duplicates"][0]["symbol"] = "ETHUSDT"
    elif mutation == "gap":
        raw["manifest"]["coverage"][0]["gaps"][0]["start"] = "2020-01-01T00:00:00Z"
    else:
        raw["manifest"]["coverage"][0]["coverage_fraction"] = "0.5"
    with pytest.raises(ValueError):
        Codec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize("field,value", [("open", "NaN"), ("volume", "Infinity"), ("trade_count", True),
    ("event_time", "garbage"), ("received_at", "2020-01-01T05:01:00+05:00"),
    ("open_time", "2020-01-01T00:00:00"), ("close_time", "2020-01-01T00:00:59.999Z")])
def test_bad_or_noncanonical_bar_encoding_rejected(field, value):
    raw = document()
    raw["bars"][0][field] = value
    with pytest.raises(ValueError):
        Codec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"null", b"not-json", b"\xff", b'{"x":1,"x":2}',
                                      b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.5}', b"[" * 1100])
def test_malformed_documents_rejected(payload):
    with pytest.raises(ValueError):
        Codec.decode(payload)


def test_byte_limit_and_bytes_only(monkeypatch):
    import src.application.historical_dataset_codec as module
    monkeypatch.setattr(module, "MAX_JSON_BYTES", 3)
    with pytest.raises(ValueError, match="byte limit"):
        Codec.encode(evidence())
    with pytest.raises(ValueError, match="bounded"):
        Codec.decode(b"1234")
    with pytest.raises(ValueError):
        Codec.decode("{}")


def test_encode_revalidates_frozen_model_copy_inputs():
    original = evidence()
    bad_bar = original.bars[0].model_copy(update={"high": Decimal(1)})
    for changed in (original.model_copy(update={"bars": (bad_bar,) + original.bars[1:]}),
                    original.model_copy(update={"manifest": original.manifest.model_copy(update={"content_checksum": "0" * 64})})):
        with pytest.raises(ValueError):
            Codec.encode(changed)


def test_missing_schema_version_rejected_instead_of_assuming_current():
    raw = document()
    del raw["manifest"]["schema_version"]
    with pytest.raises(ValueError):
        Codec.decode(json.dumps(raw).encode())
