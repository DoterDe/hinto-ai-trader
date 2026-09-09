import pytest
from fastapi.testclient import TestClient

from src.application.decision_engine import DecisionEngine
from src.application.decision_settings import DecisionSettings
from src.application.strategy_engine import StrategyEngine
from src.domain.decisions import DecisionEngineStatus, DecisionRecord
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app
from strategy_fixtures import NOW
from test_decision_integration import aligned_features
from test_feature_api import FeatureSource, feed_settings, small_settings, wait_for_source


def test_disabled_feed_reports_no_action_unavailable_without_a_new_task() -> None:
    application = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(application) as client:
        response = client.get("/decisions/status")
        assert response.status_code == 200
        status = DecisionEngineStatus.model_validate(response.json())
        assert status.evaluation_mode == "on_demand" and len(status.symbols) == 8
        assert status.policy.min_decision_agreement == pytest.approx(0.5)
        assert status.policy.min_contributing_strategies == 2
        assert all(item.outcome == "NO_ACTION" and item.readiness == "unavailable" for item in status.symbols)
        result = DecisionRecord.model_validate(client.get("/decisions/btcusdt/latest").json())
        assert result.symbol == "BTCUSDT" and result.candidate_id is None
        assert result.outcome == "NO_ACTION" and result.readiness == "unavailable"
        assert application.state.feature_engine_task is None
        assert client.get("/market/status").json()["subscriber_count"] == 0
        assert not hasattr(application.state, "decision_engine_task")


@pytest.mark.parametrize("path", ["/decisions/status", "/decisions/BTCUSDT/latest"])
def test_uninitialized_decisions_return_503(path) -> None:
    client = TestClient(create_app(settings=MarketDataSettings(enabled=False)))
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Decisions are not initialized"}
    finally:
        client.close()


@pytest.mark.parametrize("symbol", ["UNKNOWN", "invalid-symbol", "PRIVATE_ERROR_MARKER"])
def test_unknown_symbol_is_sanitized_404(symbol) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        response = client.get(f"/decisions/{symbol}/latest")
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown decision symbol"}
        assert symbol not in response.text


@pytest.mark.parametrize("path", ["/decisions/status", "/decisions/BTCUSDT/latest"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_decision_routes_are_read_only(path, method) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        assert client.request(method, path, json={"candidate": 1}).status_code == 405


def test_openapi_declares_typed_read_only_decisions_and_no_order_fields() -> None:
    schema = create_app(settings=MarketDataSettings(enabled=False)).openapi()
    for path, model in {"/decisions/status": "DecisionEngineStatus", "/decisions/{symbol}/latest": "DecisionRecord"}.items():
        assert set(schema["paths"][path]) == {"get"}
        operation = schema["paths"][path]["get"]
        assert "requestBody" not in operation
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": f"#/components/schemas/{model}"}
    fields = schema["components"]["schemas"]["DecisionRecord"]["properties"]
    assert not {"quantity", "price", "leverage", "order_type", "stop_loss", "take_profit", "execution_mode", "api_key"} & fields.keys()
    assert len(schema["paths"]) == 10


def test_offline_feature_strategy_decision_chain_uses_existing_runtime() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        response = client.get("/decisions/BTCUSDT/latest")
        assert response.status_code == 200
        decision = DecisionRecord.model_validate(response.json())
        assert decision.outcome == "NO_ACTION" and decision.readiness == "ready"
        assert client.get("/strategies/BTCUSDT/latest").json()["candidate"] is None
        assert client.get("/market/status").json()["subscriber_count"] == 1
        assert "NaN" not in response.text and "Infinity" not in response.text


def test_real_strategy_eligible_candidate_serializes_with_stable_identity() -> None:
    class Features:
        def latest(self, symbol):
            return aligned_features()
    strategies = StrategyEngine(Features(), symbols=("BTCUSDT",), clock=lambda: NOW)
    application = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(application) as client:
        application.state.decision_engine = DecisionEngine(strategies, symbols=("BTCUSDT",), clock=lambda: NOW)
        first = client.get("/decisions/BTCUSDT/latest")
        assert first.status_code == 200
        result = first.json()
        assert result["outcome"] == "ELIGIBLE" and result["direction"] == "LONG"
        assert result == client.get("/decisions/BTCUSDT/latest").json()
        assert isinstance(result["composite_score"], str) and isinstance(result["confidence"], str)
        assert result["contributing_strategies"] == ["trend_following", "momentum_continuation"]
        DecisionRecord.model_validate(result)


def test_source_failure_returns_blocked_stale_decision_without_exception_text() -> None:
    source = FeatureSource(fail=True)
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        response = client.get("/decisions/BTCUSDT/latest")
        assert response.status_code == 200
        result = DecisionRecord.model_validate(response.json())
        assert result.outcome == "BLOCKED" and result.readiness == "stale"
        assert "non-sensitive-feature-source-error-marker" not in response.text


@pytest.mark.parametrize("path", ["/decisions/status", "/decisions/BTCUSDT/latest"])
def test_unusable_provider_is_sanitized_503(path) -> None:
    class Broken:
        def latest(self, symbol):
            raise RuntimeError("private-provider-error-marker")
    application = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(application) as client:
        application.state.decision_engine = DecisionEngine(Broken(), symbols=("BTCUSDT",))
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Decisions cannot read strategy state"}
        assert "private-provider-error-marker" not in response.text


def test_decision_settings_are_read_at_startup_and_engine_is_per_lifespan(monkeypatch) -> None:
    application = create_app(settings=MarketDataSettings(enabled=False))
    monkeypatch.setenv("DECISION_MIN_CONTRIBUTING_STRATEGIES", "3")
    with TestClient(application) as client:
        first = application.state.decision_engine
        assert client.get("/decisions/status").json()["policy"]["min_contributing_strategies"] == 3
    with TestClient(application):
        assert application.state.decision_engine is not first


def test_explicit_policy_settings_override_environment(monkeypatch) -> None:
    settings = DecisionSettings(min_contributing_strategies=1)
    application = create_app(settings=MarketDataSettings(enabled=False), decision_settings=settings)
    monkeypatch.setenv("DECISION_MIN_CONTRIBUTING_STRATEGIES", "3")
    with TestClient(application) as client:
        assert client.get("/decisions/status").json()["policy"]["min_contributing_strategies"] == 1


def test_factory_and_openapi_construct_no_decision_or_feed_runtime(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("runtime must be constructed only inside lifespan")
    for name in ("DecisionEngine", "DecisionSettings", "StrategyEngine", "FeatureEngine", "BinancePublicMarketData"):
        monkeypatch.setattr(f"src.main.{name}", forbidden)
    application = create_app()
    application.openapi()
    assert not hasattr(application.state, "decision_engine")
    assert not hasattr(application.state, "market_data_task")


def test_shutdown_cancels_only_existing_tasks_and_removes_subscriber() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(enabled=False), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        assert client.get("/decisions/BTCUSDT/latest").status_code == 200
        feed, features = application.state.market_data_task, application.state.feature_engine_task
        assert client.get("/market/status").json()["subscriber_count"] == 1
        assert not hasattr(application.state, "decision_engine_task")
    assert source.closed and feed.cancelled() and features.cancelled()
    assert application.state.market_data_hub.status().subscriber_count == 0
    assert not application.state.feature_engine.running
    assert application.state.decision_engine.latest("BTCUSDT").outcome != "ELIGIBLE"
