"""Strict bounded canonical JSON. Checksum detects corruption, not authorship."""

import json

from src.application.backtest_settings import BacktestSettings
from src.application.historical_dataset_codec import _noninteger, _pairs
from src.application.validation_report import assemble_report, canonical_report_json, report_checksum
from src.domain.validation_report import MAX_REPORT_BYTES, REPORT_VERSION, ValidationReport


def verify_validation_report(report: ValidationReport) -> ValidationReport:
    report = ValidationReport.model_validate(report)
    checksum = report_checksum(report)
    if report.content_checksum != checksum or report.report_id != "validation_report_" + checksum:
        raise ValueError("validation report checksum mismatch")
    rebuilt = assemble_report(report.dataset, report.evaluation, BacktestSettings(**report.cost_baseline.model_dump()),
                              generated_at=report.generated_at)
    if rebuilt != report:
        raise ValueError("validation report derived evidence mismatch")
    return report


class ValidationReportCodec:
    @staticmethod
    def encode(report: ValidationReport) -> bytes:
        payload = canonical_report_json(verify_validation_report(report))
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError("validation report byte budget exceeded")
        return payload

    @staticmethod
    def decode(payload: bytes) -> ValidationReport:
        if not isinstance(payload, bytes) or len(payload) > MAX_REPORT_BYTES:
            raise ValueError("validation report requires bounded UTF-8 bytes")
        try:
            raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_constant=_noninteger, parse_float=_noninteger)
            if not isinstance(raw, dict) or raw.get("schema_version") != REPORT_VERSION:
                raise ValueError("explicit supported report schema is required")
            return verify_validation_report(ValidationReport.model_validate(raw))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise ValueError("invalid validation report JSON") from exc
