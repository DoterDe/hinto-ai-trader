from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("configured_mode", "expected_mode"),
    [
        (None, "paper"),
        ("paper", "paper"),
        ("PAPER", "paper"),
        ("testnet", "testnet"),
        ("TESTNET", "testnet"),
        ("live", "paper"),
        ("LIVE", "paper"),
        ("invalid-mode", "paper"),
        ("", "paper"),
    ],
)
def test_system_config_uses_only_safe_modes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    configured_mode: str | None,
    expected_mode: str,
) -> None:
    if configured_mode is None:
        monkeypatch.delenv("TRADING_MODE", raising=False)
    else:
        monkeypatch.setenv("TRADING_MODE", configured_mode)
    monkeypatch.setenv("REAL_MONEY_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AI_CAN_BYPASS_RISK_ENGINE", "true")

    response = client.get("/system/config")

    assert response.status_code == 200
    assert response.json() == {
        "app": "Hinto AI Trader",
        "mode": expected_mode,
        "real_money_execution_enabled": False,
        "ai_can_bypass_risk_engine": False,
    }


@pytest.mark.parametrize("path", ["/health", "/system/config"])
def test_public_endpoints_do_not_expose_environment_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    # Harmless configuration markers exercise filtering without using secrets.
    monkeypatch.setenv("APP_ENV", "non-sensitive-environment-marker")
    monkeypatch.setenv("INTERNAL_DIAGNOSTIC_NOTE", "non-sensitive-internal-marker")

    response = client.get(path)

    assert response.status_code == 200
    for marker in (
        "APP_ENV",
        "non-sensitive-environment-marker",
        "INTERNAL_DIAGNOSTIC_NOTE",
        "non-sensitive-internal-marker",
    ):
        assert marker not in response.text
