"""Bounded, path-free projections of a startup-loaded offline report."""

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field

from src.application.validation_report_codec import ValidationReportCodec, verify_validation_report
from src.domain.backtesting import BacktestModel, Count
from src.domain.historical_dataset import DatasetCoverage, DatasetId, MAX_SYMBOLS, UtcTime
from src.domain.models import Identifier
from src.domain.validation_costs import MAX_COST_SCENARIOS, CostScenario
from src.domain.validation_regimes import RegimeDefinition, SampleSummary
from src.domain.validation_report import MAX_REPORT_BYTES, ReportId, ValidationReport
from src.domain.walk_forward import MAX_SPLITS, WalkForwardEngineIdentity, WalkForwardProtocol

MAX_TELEMETRY_BYTES = 8 * 1024 * 1024


class ValidationMetricSummary(BacktestModel):
    evaluated_decision_count: Count
    eligible_count: Count
    blocked_count: Count
    no_action_count: Count
    completed_count: Count
    incomplete_count: Count
    boundary_censored_count: Count
    win_count: Count
    loss_count: Count
    flat_count: Count
    win_rate: Decimal | None
    mean_gross_return: Decimal | None
    mean_net_return: Decimal | None
    sum_gross_returns: Decimal
    sum_simulated_costs: Decimal
    sum_net_returns: Decimal
    normalized_max_drawdown: Decimal


class ValidationGroupSummary(BacktestModel):
    dimension: Literal["symbol", "trend", "volatility"]
    key: Identifier
    metrics: ValidationMetricSummary
    confidence: SampleSummary
    composite_score: SampleSummary
    warnings: tuple[Identifier, ...]


class ValidationCostSummary(BacktestModel):
    scenario_id: Identifier
    assumptions: CostScenario
    is_baseline: bool
    metrics: ValidationMetricSummary
    mean_cost_return: Decimal | None
    sign_changed_count: Count
    warnings: tuple[Identifier, ...]


class ValidationAnalysisSummary(BacktestModel):
    metrics: ValidationMetricSummary
    groups: tuple[ValidationGroupSummary, ...] = Field(max_length=MAX_SYMBOLS + 8)
    costs: tuple[ValidationCostSummary, ...] = Field(max_length=MAX_COST_SCENARIOS)


class ValidationWindowSummary(BacktestModel):
    split_id: Identifier
    result_id: Identifier
    ordinal: Count
    status: Identifier
    context_start: UtcTime
    context_end: UtcTime
    test_start: UtcTime
    test_end: UtcTime
    required_warmup: Count
    context_boundary_count: Count
    test_boundary_count: Count
    observed_test_boundaries: Count
    test_coverage: tuple[DatasetCoverage, ...] = Field(max_length=MAX_SYMBOLS)
    warnings: tuple[Identifier, ...]
    analysis: ValidationAnalysisSummary | None


class ValidationProjection(BacktestModel):
    report_id: ReportId
    content_checksum: str
    dataset_id: DatasetId
    dataset_status: Literal["VALID", "VALID_WITH_GAPS"]
    dataset_start: UtcTime
    dataset_end: UtcTime
    total_bars: Count
    duplicate_count: Count
    missing_bar_count: Count
    coverage: tuple[DatasetCoverage, ...] = Field(max_length=MAX_SYMBOLS)
    protocol_id: Identifier
    protocol: WalkForwardProtocol
    engines: WalkForwardEngineIdentity
    regime_definition_id: Identifier
    regime_definition: RegimeDefinition
    windows: tuple[ValidationWindowSummary, ...] = Field(max_length=MAX_SPLITS)
    aggregate: ValidationAnalysisSummary | None
    warnings: tuple[Identifier, ...]
    limitations: tuple[str, ...]


class ValidationStatus(BacktestModel):
    state: Literal["UNAVAILABLE", "READY", "INVALID"]
    reason: Literal["NO_REPORT_CONFIGURED", "REPORT_NOT_FOUND", "REPORT_INVALID", "REPORT_LOADED"]
    report_id: ReportId | None = None
    dataset_id: DatasetId | None = None
    mode: Literal["PAPER / VIRTUAL / RESEARCH ONLY"] = "PAPER / VIRTUAL / RESEARCH ONLY"
    read_only: Literal[True] = True


class ValidationSnapshot(BacktestModel):
    status: ValidationStatus
    report: ValidationProjection | None = None


def empty_validation(reason="NO_REPORT_CONFIGURED", *, invalid=False) -> ValidationSnapshot:
    return ValidationSnapshot(status=ValidationStatus(state="INVALID" if invalid else "UNAVAILABLE", reason=reason))


def _metrics(value) -> ValidationMetricSummary:
    return ValidationMetricSummary(**value.model_dump(include=set(ValidationMetricSummary.model_fields)))


def _analysis(value) -> ValidationAnalysisSummary | None:
    if value is None:
        return None
    return ValidationAnalysisSummary(metrics=_metrics(value.metrics), groups=tuple(
        ValidationGroupSummary(dimension=g.dimension, key=g.key, metrics=_metrics(g.metrics), confidence=g.confidence,
                               composite_score=g.composite_score, warnings=g.warnings) for g in value.regimes.groups),
        costs=tuple(ValidationCostSummary(scenario_id=c.scenario_id, assumptions=c.assumptions, is_baseline=c.is_baseline,
            metrics=_metrics(c.metrics), mean_cost_return=c.mean_cost_return,
            sign_changed_count=len(c.sign_changed_decision_ids), warnings=c.warnings) for c in value.costs))


def project_validation(report: ValidationReport) -> ValidationSnapshot:
    report = verify_validation_report(report)
    from src.strategies.identity import identity
    definition = RegimeDefinition()
    windows = tuple(ValidationWindowSummary(**window.split.model_dump(include={
        "split_id", "ordinal", "context_start", "context_end", "test_start", "test_end", "required_warmup",
        "context_boundary_count", "test_boundary_count", "observed_test_boundaries", "test_coverage"}),
        result_id=window.result_id, status=window.status, warnings=window.warnings, analysis=_analysis(analysis.analysis))
        for window, analysis in zip(report.evaluation.windows, report.windows))
    projection = ValidationProjection(report_id=report.report_id, content_checksum=report.content_checksum,
        dataset_id=report.dataset.dataset_id, dataset_status=report.dataset.status,
        dataset_start=report.dataset.start, dataset_end=report.dataset.end, total_bars=report.dataset.total_bars,
        duplicate_count=report.dataset.duplicate_count, missing_bar_count=report.dataset.missing_bar_count,
        coverage=report.dataset.coverage, protocol_id=report.evaluation.plan.protocol_id,
        protocol=report.evaluation.protocol, engines=report.evaluation.engines,
        regime_definition_id=identity("regime_definition", definition), regime_definition=definition,
        windows=windows, aggregate=_analysis(report.aggregate), warnings=report.warnings, limitations=report.limitations)
    snapshot = ValidationSnapshot(status=ValidationStatus(state="READY", reason="REPORT_LOADED",
        report_id=report.report_id, dataset_id=report.dataset.dataset_id), report=projection)
    if len(snapshot.model_dump_json().encode("utf-8")) > MAX_TELEMETRY_BYTES:
        raise ValueError("validation telemetry byte budget exceeded")
    return snapshot


def load_validation(path: str | Path | None) -> ValidationSnapshot:
    """Server configuration only; called once at startup, never by HTTP reads."""
    if not path:
        return empty_validation()
    try:
        with Path(path).open("rb") as stream:
            payload = stream.read(MAX_REPORT_BYTES + 1)
        return project_validation(ValidationReportCodec.decode(payload))
    except FileNotFoundError:
        return empty_validation("REPORT_NOT_FOUND")
    except (OSError, ValueError):
        return empty_validation("REPORT_INVALID", invalid=True)
