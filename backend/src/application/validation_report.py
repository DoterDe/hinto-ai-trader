"""Assemble existing evidence and metrics, without tuning or analytical replay."""

import hashlib
import json
from datetime import datetime

from src.application.backtest_identity import settings_identity
from src.application.backtest_metrics import calculate_metrics
from src.application.backtest_settings import BacktestSettings
from src.application.historical_dataset import verify_historical_dataset
from src.application.historical_dataset_codec import _value
from src.application.validation_costs import analyze_costs
from src.application.validation_metrics import validation_metrics
from src.application.validation_regimes import analyze_regimes
from src.application.walk_forward import protocol_identity
from src.domain.historical_dataset import HistoricalDataset
from src.domain.validation_report import (
    MAX_REPORT_BYTES, MAX_REPORT_DECISIONS, MAX_REPORT_GROUPS, ValidationAnalysis, ValidationCostBaseline,
    ValidationReport, ValidationWindowAnalysis,
)
from src.domain.walk_forward import WalkForwardEvaluation
from src.strategies.identity import identity

LIMITATIONS = (
    "Historical validation is not a prediction. Historical hit rate is not a future probability of profit.",
    "Confidence measures analytical evidence/agreement quality, not probability of profit.",
    "Context warms fixed production features; test data never fits parameters. No strategy/settings ranking.",
    "Signal returns and additive normalized drawdown are not allocated portfolio PnL or account equity.",
    "Missing bars stay missing. Incomplete outcomes never receive fabricated exits or returns.",
    "Window-end censoring is retained when pooling disjoint test cohorts. Overlap disables pooled aggregates.",
    "Regime thresholds are fixed engineering partitions, not empirically estimated trading thresholds.",
    "OHLCV alone cannot establish intrabar execution, full liquidity, funding payments or a reconstructed order book.",
)


def canonical_report_json(value) -> bytes:
    return (json.dumps(_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def report_checksum(report: ValidationReport) -> str:
    return hashlib.sha256(canonical_report_json(report.model_dump(
        exclude={"report_id", "content_checksum", "generated_at"}))).hexdigest()


def _analysis(observations, outcomes, evidence, symbols, costs, **cutoffs) -> ValidationAnalysis:
    return ValidationAnalysis(metrics=validation_metrics(observations, outcomes, **cutoffs),
        regimes=analyze_regimes(observations, outcomes, tuple(item.regime for item in evidence), symbols=symbols, **cutoffs),
        costs=analyze_costs(observations, outcomes, costs, **cutoffs))


def verify_evaluation(evaluation: WalkForwardEvaluation) -> WalkForwardEvaluation:
    """Check internal provenance and identities; not a claim of external authenticity."""
    evaluation = WalkForwardEvaluation.model_validate(evaluation)
    plan, protocol = evaluation.plan, evaluation.protocol
    if (plan.protocol_id != protocol_identity(protocol) or plan.dataset_id != protocol.dataset_id or
            tuple(window.split for window in evaluation.windows) != plan.splits):
        raise ValueError("evaluation protocol/split provenance mismatch")
    if sum(len(window.decisions) for window in evaluation.windows) > MAX_REPORT_DECISIONS:
        raise ValueError("validation report decision budget exceeded")
    if (len(protocol.symbols) + 8) * (len(evaluation.windows) + 1) > MAX_REPORT_GROUPS:
        raise ValueError("validation report group budget exceeded")
    for window in evaluation.windows:
        if window.engines != evaluation.engines:
            raise ValueError("window engine settings changed")
        expected = identity("walk_window", dict(split=window.split.model_dump(exclude={"dataset_id"}),
            **window.model_dump(exclude={"result_id", "split"})))
        if window.result_id != expected:
            raise ValueError("window content identity mismatch")
        if window.metrics is not None and window.metrics != calculate_metrics(window.decisions, window.outcomes, cutoff=window.split.test_end):
            raise ValueError("window metrics mismatch")
        for decision, evidence in zip(window.decisions, window.evidence):
            if (evidence.decision_id != decision.decision.decision_id or evidence.symbol != decision.decision.symbol or
                    evidence.boundary != decision.source_bar_close_time or evidence.regime.symbol != evidence.symbol or
                    evidence.regime.boundary != evidence.boundary or
                    not window.split.test_start <= decision.source_bar_open_time < window.split.test_end):
                raise ValueError("test evidence provenance mismatch")
    expected = identity("walk_evaluation", (protocol.dataset_id, plan.protocol_id, evaluation.engines,
                        plan.status, tuple(window.result_id for window in evaluation.windows)))
    if evaluation.evaluation_id != expected:
        raise ValueError("evaluation identity mismatch")
    return evaluation


def assemble_report(dataset_manifest, evaluation, costs, *, generated_at=None) -> ValidationReport:
    evaluation = verify_evaluation(evaluation)
    costs = BacktestSettings.model_validate(costs)
    if (dataset_manifest.dataset_id != evaluation.protocol.dataset_id or dataset_manifest.symbols != evaluation.protocol.symbols or
            dataset_manifest.interval != evaluation.protocol.interval or settings_identity(costs) != evaluation.engines.backtest_settings_id):
        raise ValueError("report dataset/settings provenance mismatch")
    baseline = ValidationCostBaseline(**costs.model_dump())
    windows, warnings = [], set()
    decisions, outcomes, evidence, cutoffs = [], [], [], {}
    for window in evaluation.windows:
        warnings.update(window.warnings)
        if window.status != "EVALUATED":
            warnings.add(window.status)
            analysis = None
        else:
            analysis = _analysis(window.decisions, window.outcomes, window.evidence, evaluation.protocol.symbols,
                                 costs, cutoff=window.split.test_end)
            decisions.extend(window.decisions)
            outcomes.extend(window.outcomes)
            evidence.extend(window.evidence)
            cutoffs.update((item.decision.decision_id, window.split.test_end) for item in window.decisions)
        windows.append(ValidationWindowAnalysis(window_result_id=window.result_id, analysis=analysis))
    if dataset_manifest.gap_count:
        warnings.add("VALID_WITH_GAPS")
    if dataset_manifest.duplicate_count:
        warnings.add("IDENTICAL_INPUT_DUPLICATES")
    if evaluation.plan.status != "READY":
        warnings.add(evaluation.plan.status)
    aggregate = None
    if evaluation.protocol.allow_test_overlap:
        warnings.add("OVERLAP_AGGREGATE_WITHHELD")
    else:
        aggregate = _analysis(tuple(decisions), tuple(outcomes), tuple(evidence), evaluation.protocol.symbols, costs, cutoffs=cutoffs)
    all_analyses = [item.analysis for item in windows if item.analysis is not None] + ([aggregate] if aggregate else [])
    if any(group.warnings for analysis in all_analyses for group in analysis.regimes.groups):
        warnings.add("SPARSE_OR_EMPTY_GROUPS")
    if not decisions:
        warnings.add("NO_EVALUATED_TEST_DECISIONS")
    if decisions and not outcomes:
        warnings.add("VALID_NO_SIGNALS")
    payload = dict(dataset=dataset_manifest, evaluation=evaluation, cost_baseline=baseline,
                   windows=tuple(windows), aggregate=aggregate, warnings=tuple(sorted(warnings)),
                   limitations=LIMITATIONS, generated_at=generated_at)
    provisional = ValidationReport(report_id="validation_report_" + "0" * 64, content_checksum="0" * 64, **payload)
    checksum = report_checksum(provisional)
    report = ValidationReport(report_id="validation_report_" + checksum, content_checksum=checksum, **payload)
    if len(canonical_report_json(report)) > MAX_REPORT_BYTES:
        raise ValueError("validation report byte budget exceeded")
    return report


def build_validation_report(dataset: HistoricalDataset, evaluation: WalkForwardEvaluation,
                            costs: BacktestSettings, *, generated_at: datetime | None = None) -> ValidationReport:
    dataset = verify_historical_dataset(dataset)
    return assemble_report(dataset.manifest, evaluation, costs, generated_at=generated_at)
