import json
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from backtest_fixtures import START, bar
from test_walk_forward_evaluator import dataset, protocol
from src.application.backtest_settings import BacktestSettings
from src.application.validation_report import build_validation_report, canonical_report_json, report_checksum
from src.application.validation_report_codec import ValidationReportCodec
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.validation_report import ValidationReport


@pytest.fixture(scope="module")
def report():
    import asyncio
    from src.application.validation_example import example_report
    return asyncio.run(example_report())


def test_report_exact_codec_roundtrip_and_statistical_context(report):
    payload = ValidationReportCodec.encode(report)
    assert ValidationReportCodec.decode(payload) == report
    assert ValidationReportCodec.encode(ValidationReportCodec.decode(payload)) == payload
    assert report.report_id == "validation_report_" + report.content_checksum
    assert report_checksum(report) == report.content_checksum
    assert all(item.analysis is not None for item in report.windows)
    aggregate = report.aggregate.metrics
    assert aggregate.evaluated_decision_count == 35  # 50 context bars excluded
    assert aggregate.completed_count > 0 and aggregate.incomplete_count > 0
    assert aggregate.boundary_censored_count == sum(item.metrics.boundary_censored_count for item in report.evaluation.windows)
    assert aggregate.eligible_count == sum(item.metrics.eligible_count for item in report.evaluation.windows)
    assert "SPARSE_OR_EMPTY_GROUPS" in report.warnings
    assert len(report.aggregate.regimes.groups) == 9
    assert all(g.metrics.boundary_censored_count <= g.metrics.incomplete_count for g in report.aggregate.regimes.groups)
    assert next(c for c in report.aggregate.costs if c.is_baseline).metrics == aggregate
    assert any("not a future probability" in item for item in report.limitations)
    assert b'"ema_separation_deadband":"5e-4"' in payload
    assert b'NaN' not in payload and b'Infinity' not in payload


def test_generated_at_is_outside_content_identity(report):
    other = report.model_copy(update={"generated_at": START})
    assert report_checksum(other) == report.content_checksum
    assert ValidationReportCodec.decode(ValidationReportCodec.encode(other)) == other
    assert report.generated_at is None
    with pytest.raises(ValueError):
        ValidationReportCodec.encode(report.model_copy(update={"generated_at": START.replace(tzinfo=None)}))


@pytest.mark.parametrize("mutation", ["checksum", "version", "unknown", "metric", "dataset", "rule", "window", "evaluation", "nonfinite", "float", "duplicate"])
def test_corrupt_unknown_unsafe_or_mismatched_json_is_rejected(report, mutation):
    payload = ValidationReportCodec.encode(report)
    raw = json.loads(payload)
    if mutation == "checksum": raw["content_checksum"] = "0" * 64
    elif mutation == "version": raw["schema_version"] = "validation-report-v999"
    elif mutation == "unknown": raw["arbitrary"] = "rejected"
    elif mutation == "metric": raw["aggregate"]["metrics"]["sum_net_returns"] = "9e2"
    elif mutation == "dataset": raw["dataset"]["dataset_id"] = "historical_dataset_" + "0" * 64
    elif mutation == "rule": raw["aggregate"]["regimes"]["definition"]["normalized_atr_low_upper"] = ".9"
    elif mutation == "window": raw["evaluation"]["windows"][0]["result_id"] = "wrong"
    elif mutation == "evaluation": raw["evaluation"]["evaluation_id"] = "wrong"
    elif mutation == "nonfinite": raw["aggregate"]["metrics"]["sum_net_returns"] = "NaN"
    elif mutation == "float": raw["aggregate"]["metrics"]["sum_net_returns"] = 0.1
    else:
        payload = payload.replace(b'{', b'{"schema_version":"validation-report-v1",', 1)
    if mutation != "duplicate": payload = json.dumps(raw).encode()
    with pytest.raises(ValueError): ValidationReportCodec.decode(payload)


def test_recomputed_checksum_cannot_hide_inconsistent_derived_metrics(report):
    metrics = report.aggregate.metrics.model_copy(update={"sum_net_returns": Decimal(999)})
    altered = report.model_copy(update={"aggregate": report.aggregate.model_copy(update={"metrics": metrics})})
    checksum = report_checksum(altered)
    altered = altered.model_copy(update={"content_checksum": checksum, "report_id": "validation_report_" + checksum})
    with pytest.raises(ValueError, match="derived evidence"):
        ValidationReportCodec.encode(altered)


def test_report_precision_and_input_immutability(report):
    before = report.model_dump_json()
    payload = ValidationReportCodec.encode(report)
    with localcontext() as context:
        context.prec = 4
        assert ValidationReportCodec.encode(report) == payload
    assert report.model_dump_json() == before
    with pytest.raises(ValueError): report.warnings = ()


@pytest.mark.asyncio
async def test_overlap_disables_pooled_statistics_but_preserves_windows():
    data = dataset(count=80)
    engine = WalkForwardEvaluator(protocol(data, step_boundaries=10, allow_test_overlap=True))
    report = build_validation_report(data, await engine.run(data), engine.backtest_settings)
    assert report.aggregate is None
    assert "OVERLAP_AGGREGATE_WITHHELD" in report.warnings
    assert all(window.analysis is not None for window in report.windows)
    assert ValidationReportCodec.decode(ValidationReportCodec.encode(report)) == report


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["short", "no_signals", "gap"])
async def test_missing_rejected_and_no_signal_reports_are_distinct(kind):
    rows = [bar(i, opened="100", closed="100") for i in range(70 if kind != "short" else 20)]
    if kind == "gap": rows.pop(10)
    data = dataset(rows)
    engine = WalkForwardEvaluator(protocol(data))
    report = build_validation_report(data, await engine.run(data), engine.backtest_settings)
    assert report.aggregate.metrics.completed_count == 0
    if kind == "no_signals":
        assert report.aggregate.metrics.evaluated_decision_count == 20 and "VALID_NO_SIGNALS" in report.warnings
    else:
        assert report.aggregate.metrics.evaluated_decision_count == 0
        assert "NO_EVALUATED_TEST_DECISIONS" in report.warnings and "INSUFFICIENT_CONTEXT" in report.warnings
    if kind == "gap": assert "VALID_WITH_GAPS" in report.warnings


@pytest.mark.asyncio
async def test_changed_protocol_cost_or_dataset_changes_identity_and_input_permutation_does_not():
    first = dataset(count=80)
    reversed_data = dataset(reversed(first.bars))
    results = []
    for data, width, costs in ((first, 30, BacktestSettings()), (reversed_data, 30, BacktestSettings()),
                               (first, 20, BacktestSettings()), (first, 30, BacktestSettings(fee_bps_per_side=7))):
        engine = WalkForwardEvaluator(protocol(data, test_boundaries=width, step_boundaries=width), backtest_settings=costs)
        results.append(build_validation_report(data, await engine.run(data), costs))
    assert ValidationReportCodec.encode(results[0]) == ValidationReportCodec.encode(results[1])
    assert len({item.report_id for item in results}) == 3


def test_report_size_and_decision_limits(report, monkeypatch):
    import src.application.validation_report_codec as codec
    import src.application.validation_report as builder
    monkeypatch.setattr(codec, "MAX_REPORT_BYTES", 100)
    with pytest.raises(ValueError): ValidationReportCodec.encode(report)
    with pytest.raises(ValueError): ValidationReportCodec.decode(b" " * 101)
    monkeypatch.setattr(builder, "MAX_REPORT_DECISIONS", 1)
    with pytest.raises(ValueError, match="decision budget"):
        builder.verify_evaluation(report.evaluation)


def test_report_group_and_assembly_byte_budgets(report, monkeypatch):
    import src.application.validation_report as builder
    with monkeypatch.context() as patch:
        patch.setattr(builder, "MAX_REPORT_GROUPS", 1)
        with pytest.raises(ValueError, match="group budget"):
            builder.verify_evaluation(report.evaluation)
    monkeypatch.setattr(builder, "MAX_REPORT_BYTES", 100)
    with pytest.raises(ValueError, match="byte budget"):
        builder.assemble_report(report.dataset, report.evaluation, BacktestSettings(**report.cost_baseline.model_dump()))


@pytest.mark.asyncio
async def test_export_mode_is_honored_for_synthetic_input(report):
    from scripts.export_validation_report import export
    from types import SimpleNamespace
    # Real CLI orchestration; in-memory capture avoids leaving an artifact.
    class Destination:
        payload = None

        def write_bytes(self, value):
            self.payload = value
    destination = Destination()
    await export(SimpleNamespace(dataset=None, mode="ROLLING", check=False, output=destination))
    changed = ValidationReportCodec.decode(destination.payload)
    assert changed.evaluation.protocol.mode == "ROLLING"
    assert changed.dataset.dataset_id == report.dataset.dataset_id
    assert changed.report_id != report.report_id
