import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from src.application.validation_example import example_report
from src.application.validation_report_codec import ValidationReportCodec
from src.application.validation_telemetry import ValidationSnapshot, load_validation, project_validation
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app


@pytest.fixture(scope="module")
def exported_report():
    return asyncio.run(example_report())


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/validation/status", "/validation/latest"])
async def test_unavailable_get_is_explicit_and_has_no_path_or_file_action(path):
    app = create_app(settings=MarketDataSettings(enabled=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert "NO_REPORT_CONFIGURED" in response.text
    assert "PAPER / VIRTUAL / RESEARCH ONLY" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/validation/status", "/validation/latest"])
async def test_non_get_actions_are_rejected(method, path):
    app = create_app(settings=MarketDataSettings(enabled=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        assert (await client.request(method, path)).status_code == 405


def test_startup_loads_once_gets_are_inert_and_shutdown_clean(exported_report, tmp_path, monkeypatch):
    path = tmp_path / "local-report.json"
    path.write_bytes(ValidationReportCodec.encode(exported_report))
    app = create_app(settings=MarketDataSettings(enabled=False), validation_report_path=str(path))
    with TestClient(app) as client:
        first = client.get("/validation/latest")
        result = ValidationSnapshot.model_validate(first.json())
        assert result.status.state == "READY"
        assert result.report.report_id == exported_report.report_id
        assert result.report.aggregate.metrics.incomplete_count > 0
        assert "SPARSE_OR_EMPTY_GROUPS" in result.report.warnings
        assert str(tmp_path) not in first.text and "source_label" not in first.text
        assert "decisions\":" not in first.text and "entry_price_raw" not in first.text
        path.write_text("invalid after startup", encoding="utf-8")

        def forbidden(*args, **kwargs): raise AssertionError("GET cannot load or compute")
        monkeypatch.setattr("src.main.load_validation", forbidden)
        monkeypatch.setattr("src.application.walk_forward_evaluator.WalkForwardEvaluator.run", forbidden)
        assert client.get("/validation/latest").content == first.content
        assert client.get("/validation/status").json()["report_id"] == exported_report.report_id
    assert app.state.market_data_task.done()
    assert app.state.market_data_hub.status().subscriber_count == 0


@pytest.mark.parametrize("kind,reason", [("missing", "REPORT_NOT_FOUND"), ("invalid", "REPORT_INVALID"), ("large", "REPORT_INVALID")])
def test_unavailable_or_invalid_file_has_sanitized_reason(tmp_path, kind, reason, monkeypatch):
    path = tmp_path / "hidden-local-path.json"
    if kind == "invalid": path.write_text("not a report", encoding="utf-8")
    if kind == "large":
        monkeypatch.setattr("src.application.validation_telemetry.MAX_REPORT_BYTES", 8)
        path.write_bytes(b" " * 9)
    snapshot = load_validation(path)
    assert snapshot.status.reason == reason and snapshot.report is None
    assert "hidden-local-path" not in snapshot.model_dump_json()


def test_projection_and_exported_json_schema_reconcile(exported_report):
    from scripts.export_dashboard_contract import artifacts
    schema_path = next(path for path in artifacts() if path.name == "validation.schema.json")
    schema = json.loads(artifacts()[schema_path])
    assert schema["required"] == ["status", "report"]
    projection = project_validation(exported_report)
    assert ValidationSnapshot.model_validate_json(projection.model_dump_json()) == projection
    assert len(projection.report.windows) == len(exported_report.windows)
    paths = create_app().openapi()["paths"]
    assert len(paths) == 21 and all(set(methods) == {"get"} for methods in paths.values())


def test_projection_byte_budget_rejects_oversize_evidence(exported_report, monkeypatch):
    monkeypatch.setattr("src.application.validation_telemetry.MAX_TELEMETRY_BYTES", 100)
    with pytest.raises(ValueError, match="telemetry byte budget"):
        project_validation(exported_report)
