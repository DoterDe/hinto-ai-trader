from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.application.strategy_engine import StrategyEngine
from src.application.strategy_settings import StrategySettings
from src.domain.strategies import StrategyEngineStatus, StrategyId, StrategySnapshot
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app
from strategy_fixtures import NOW, positive_momentum
from test_feature_api import FeatureSource, feed_settings, small_settings, wait_for_source


def test_disabled_feed_exposes_unavailable_strategies_without_new_runtime() -> None:
    app = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(app) as client:
        response = client.get("/strategies/status")
        assert response.status_code == 200
        status = StrategyEngineStatus.model_validate(response.json())
        assert status.evaluation_mode == "on_demand"
        assert len(status.strategies) == 3 and len(status.symbols) == 8
        assert all(item.readiness == "unavailable" and not item.candidate_available for item in status.symbols)
        result = StrategySnapshot.model_validate(client.get("/strategies/btcusdt/latest").json())
        assert result.symbol == "BTCUSDT" and result.readiness == "unavailable"
        assert result.composite_score is result.confidence is result.candidate is None
        assert all(item.score is None and item.reasons for item in result.assessments)
        assert app.state.feature_engine_task is None
        assert client.get("/market/status").json()["subscriber_count"] == 0
        assert not hasattr(app.state, "strategy_engine_task")


@pytest.mark.parametrize("path", ["/strategies/status", "/strategies/BTCUSDT/latest"])
def test_strategy_routes_before_initialization_return_503(path: str) -> None:
    client = TestClient(create_app(settings=MarketDataSettings(enabled=False)))
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Strategies are not initialized"}
    finally:
        client.close()


@pytest.mark.parametrize("symbol", ["UNKNOWN", "invalid-symbol", "PRIVATE_DIAGNOSTIC_MARKER"])
def test_unknown_symbols_have_sanitized_404(symbol: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        response = client.get(f"/strategies/{symbol}/latest")
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown strategy symbol"}
        assert symbol not in response.text


@pytest.mark.parametrize("path", ["/strategies/status", "/strategies/BTCUSDT/latest"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_strategy_endpoints_are_read_only(path: str, method: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        assert client.request(method, path, json={"feature": 100}).status_code == 405


def test_openapi_exposes_typed_analytical_responses_and_no_arbitrary_feature_input() -> None:
    schema = create_app(settings=MarketDataSettings(enabled=False)).openapi()
    for path, model in {"/strategies/status": "StrategyEngineStatus",
                        "/strategies/{symbol}/latest": "StrategySnapshot"}.items():
        assert set(schema["paths"][path]) == {"get"}
        operation = schema["paths"][path]["get"]
        assert "requestBody" not in operation
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{model}"}
    candidate = schema["components"]["schemas"]["StrategyCandidate"]["properties"]
    assert not {"quantity", "leverage", "order_type", "trade_intent", "execution_mode"} & candidate.keys()
    assert len(schema["paths"]) == 10


def test_real_feature_engine_closed_history_drives_read_only_assessments() -> None:
    source = FeatureSource()
    app = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(app) as client:
        wait_for_source(client, source)
        response = client.get("/strategies/btcusdt/latest")
        assert response.status_code == 200
        result = StrategySnapshot.model_validate(response.json())
        assert result.readiness == "ready" and len(result.assessments) == 3
        assert all(item.readiness == "ready" for item in result.assessments)
        # Closed history has ATR=3 / close=16 > hard .05; rising-only RSI=100
        # suppresses continuation. The open candle at 999 is never scored.
        assert [item.score for item in result.assessments] == [0, 0, 0]
        assert result.candidate is None
        momentum = result.assessments[1]
        values = {item.name: item.value for item in momentum.evidence}
        assert values["rsi_continuation"] == 100
        # Change=2, VWAP=(14*6 + 16*8)/(6+8)=106/7, ratio=7/53.
        assert Decimal("0.13207547169811320") < values["close_change_over_vwap"] < Decimal("0.13207547169811321")
        first_id = result.observation_id
        assert StrategySnapshot.model_validate(client.get("/strategies/BTCUSDT/latest").json()).observation_id == first_id
        assert client.get("/strategies/status").json()["symbols"][0]["readiness"] == "ready"
        assert "NaN" not in response.text and "Infinity" not in response.text
        assert client.get("/market/status").json()["subscriber_count"] == 1


def test_default_feature_warmup_has_no_scores_or_candidate() -> None:
    source = FeatureSource()
    app = create_app(settings=feed_settings(), source=source)
    with TestClient(app) as client:
        wait_for_source(client, source)
        result = StrategySnapshot.model_validate(client.get("/strategies/BTCUSDT/latest").json())
        assert result.readiness == "warming_up"
        assert result.candidate is None and result.composite_score is None
        assert all(item.readiness == "warming_up" and item.score is None for item in result.assessments)


def test_stale_optional_book_preserves_candle_strategy_readiness() -> None:
    source = FeatureSource(book_age=60)
    app = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(app) as client:
        wait_for_source(client, source)
        result = StrategySnapshot.model_validate(client.get("/strategies/BTCUSDT/latest").json())
        assert all(item.readiness == "ready" for item in result.assessments)
        assert any("microstructure:optional_" in reason for reason in result.assessments[1].reasons)


def test_failed_public_source_prevents_any_directional_candidate() -> None:
    source = FeatureSource(fail=True)
    app = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(app) as client:
        wait_for_source(client, source)
        response = client.get("/strategies/BTCUSDT/latest")
        result = StrategySnapshot.model_validate(response.json())
        assert result.readiness == "stale" and result.candidate is None
        assert all(item.score is None for item in result.assessments)
        assert "non-sensitive-feature-source-error-marker" not in response.text
        assert client.get("/health").status_code == 200


def test_candidate_response_has_deterministic_id_and_decimal_strings() -> None:
    # Direct engine injection tests candidate serialization without changing
    # the HTTP contract to accept fabricated feature inputs.
    class Provider:
        def latest(self, symbol: str):
            return positive_momentum()

    app = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(app) as client:
        app.state.strategy_engine = StrategyEngine(Provider(),
            StrategySettings(enabled_strategies=(StrategyId.MOMENTUM,)), symbols=("BTCUSDT",), clock=lambda: NOW)
        first = client.get("/strategies/BTCUSDT/latest")
        assert first.status_code == 200
        result = first.json()
        assert result == client.get("/strategies/BTCUSDT/latest").json()
        assert result["candidate"]["composite_score"] == "100"
        assert result["candidate"]["confidence"] == "1"
        assert result["direction"] == "LONG"
        StrategySnapshot.model_validate(result)


def test_strategy_settings_are_loaded_only_at_startup_and_engine_is_per_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(settings=MarketDataSettings(enabled=False))
    monkeypatch.setenv("STRATEGY_TREND_WEIGHT", "2")
    with TestClient(app) as client:
        engine = app.state.strategy_engine
        assert client.get("/strategies/status").json()["strategies"][0]["aggregation_weight"] == "2"
    with TestClient(app):
        assert app.state.strategy_engine is not engine


def test_factory_has_no_strategy_or_market_runtime_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("runtime must only be constructed inside lifespan")

    for name in ("StrategyEngine", "StrategySettings", "FeatureEngine", "BinancePublicMarketData"):
        monkeypatch.setattr(f"src.main.{name}", unexpected)
    app = create_app()
    app.openapi()
    assert not hasattr(app.state, "strategy_engine")
    assert not hasattr(app.state, "market_data_task")


def test_shutdown_still_cancels_feed_and_feature_tasks_with_no_extra_subscriber() -> None:
    source = FeatureSource()
    app = create_app(settings=feed_settings(enabled=False), source=source, feature_settings=small_settings())
    with TestClient(app) as client:
        wait_for_source(client, source)
        assert client.get("/strategies/BTCUSDT/latest").status_code == 200
        assert client.get("/market/status").json()["subscriber_count"] == 1
        feed, features = app.state.market_data_task, app.state.feature_engine_task
        assert not hasattr(app.state, "strategy_engine_task")
    assert feed.cancelled() and features.cancelled() and source.closed
    assert app.state.market_data_hub.status().subscriber_count == 0
    assert not app.state.feature_engine.running
    assert app.state.strategy_engine.latest("BTCUSDT").candidate is None
