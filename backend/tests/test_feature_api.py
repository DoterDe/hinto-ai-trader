import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.application.feature_settings import FeatureSettings
from src.domain.features import FeatureEngineStatus, FeatureSnapshot
from src.domain.market_data import (
    BookTickerEvent, ConnectionStatus, EventType, KlineEvent,
    MarketConnectionState, MarketDataSink, MarkPriceEvent, TradeEvent,
)
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app


GROUPS = ("trade", "returns", "trend", "momentum", "volatility", "volume",
          "microstructure", "mark_funding", "regime")
CANDLE_GROUPS = ("returns", "trend", "momentum", "volatility", "volume", "regime")


def small_settings() -> FeatureSettings:
    return FeatureSettings(
        ema_fast=1, ema_slow=2, ema_long=3, rsi_period=2, atr_period=2,
        roc_period=2, volatility_window=2, relative_volume_window=2,
        vwap_window=2, rolling_return_windows=(1, 2), history_limit=5,
    )


def feed_settings(**overrides: Any) -> MarketDataSettings:
    return MarketDataSettings(**(dict(enabled=True, symbols=("BTCUSDT",)) | overrides))


class FeatureSource:
    """Offline normalized observations, including a current open candle."""

    def __init__(self, *, book_age: float = 0, fail: bool = False) -> None:
        self.book_age = book_age
        self.fail = fail
        self.ready = asyncio.Event()
        self.closed = False
        self.loop: asyncio.AbstractEventLoop | None = None

    async def run(self, sink: MarketDataSink) -> None:
        self.loop = asyncio.get_running_loop()
        now = datetime.now(timezone.utc)
        minute = now.replace(second=0, microsecond=0)
        sink.update_connection(MarketConnectionState(
            connection_id="feature_fixture", event_types=tuple(EventType),
            status=ConnectionStatus.CONNECTED, changed_at=now, generation=1,
        ))
        try:
            # One first historical observation may be discarded on source setup;
            # three following closed candles establish this fixture's warm-up.
            for index in range(4):
                opened = minute - timedelta(minutes=4 - index)
                ended = opened + timedelta(minutes=1)
                close, volume = Decimal(10 + index * 2), Decimal(2 + index * 2)
                sink.publish(KlineEvent(
                    symbol="BTCUSDT", event_time=ended, received_at=now, interval="1m",
                    open_time=opened, close_time=ended - timedelta(milliseconds=1),
                    open=close, high=close + 1, low=close - 1, close=close,
                    volume=volume, quote_volume=volume * close, trade_count=index + 1,
                    is_closed=True, taker_buy_volume=volume / 2,
                    taker_buy_quote_volume=volume * close / 2,
                ), connection_id="feature_fixture")
                await asyncio.sleep(0)
            common = dict(symbol="BTCUSDT", event_time=now, received_at=now)
            sink.publish(KlineEvent(
                **common, interval="1m", open_time=minute,
                close_time=minute + timedelta(minutes=1) - timedelta(milliseconds=1),
                open="999", high="1000", low="998", close="999",
                volume="2", quote_volume="1998", trade_count=1, is_closed=False,
                taker_buy_volume="1", taker_buy_quote_volume="999",
            ), connection_id="feature_fixture")
            sink.publish(TradeEvent(
                **common, aggregate_trade_id=1, first_trade_id=1, last_trade_id=2,
                price="12345.123456789012345678", quantity="0.001", trade_time=now,
                buyer_is_maker=False,
            ), connection_id="feature_fixture")
            observed = now - timedelta(seconds=self.book_age)
            sink.publish(BookTickerEvent(
                **(common | {"event_time": observed}), update_id=1, bid_price="99",
                ask_price="101", bid_quantity="3", ask_quantity="1", transaction_time=observed,
            ), connection_id="feature_fixture")
            sink.publish(MarkPriceEvent(
                **common, mark_price="102", index_price="100", funding_rate="-0.0001",
                next_funding_time=now + timedelta(hours=8),
            ), connection_id="feature_fixture")
            self.ready.set()
            if self.fail:
                raise RuntimeError("non-sensitive-feature-source-error-marker")
            await asyncio.Event().wait()
        finally:
            self.closed = True


def wait_for_source(client: TestClient, source: FeatureSource) -> None:
    assert client.portal is not None

    async def wait() -> None:
        await asyncio.wait_for(source.ready.wait(), timeout=2)

    client.portal.call(wait)


def test_disabled_features_report_missing_groups_without_consumer_task() -> None:
    application = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(application) as client:
        response = client.get("/features/status")
        assert response.status_code == 200
        status = FeatureEngineStatus.model_validate(response.json())
        assert status.running is False
        assert status.interval == "1m" and status.history_limit == 500
        assert len(status.symbols) == 8
        for symbol in status.symbols:
            assert symbol.state == "unavailable"
            assert symbol.closed_candles == 0
            assert {group.name for group in symbol.groups} == set(GROUPS)
            assert all(group.state == "unavailable" and group.reasons for group in symbol.groups)
        snapshot = client.get("/features/btcusdt/latest").json()
        assert snapshot["symbol"] == "BTCUSDT"
        assert snapshot["state"] == "unavailable"
        assert snapshot["closed_candle_time"] is None
        assert all(snapshot[name]["values"] is None for name in GROUPS)
        assert application.state.feature_engine_task is None
        assert client.get("/market/status").json()["subscriber_count"] == 0


@pytest.mark.parametrize("path", ["/features/status", "/features/BTCUSDT/latest"])
def test_feature_routes_before_lifespan_are_unavailable(path: str) -> None:
    client = TestClient(create_app(settings=MarketDataSettings(enabled=False)))
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Features are not initialized"}
    finally:
        client.close()


@pytest.mark.parametrize("symbol", ["UNKNOWN", "invalid-symbol", "INTERNAL_DIAGNOSTIC_NOTE"])
def test_unknown_feature_symbols_have_sanitized_404(symbol: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        response = client.get(f"/features/{symbol}/latest")
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown feature symbol"}
        assert symbol not in response.text


@pytest.mark.parametrize("path", ["/features/status", "/features/BTCUSDT/latest"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_feature_routes_are_read_only(path: str, method: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        assert client.request(method, path, json={}).status_code == 405


def test_openapi_declares_typed_read_only_feature_contracts() -> None:
    schema = create_app(settings=MarketDataSettings(enabled=False)).openapi()
    expected = {"/features/status": "FeatureEngineStatus",
                "/features/{symbol}/latest": "FeatureSnapshot"}
    for path, model in expected.items():
        assert set(schema["paths"][path]) == {"get"}
        response_schema = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model}"}
    assert set(schema["paths"]) == {"/health", "/system/config", "/market/status",
                                     "/market/{symbol}/latest", *expected}


def test_ready_feature_api_uses_closed_history_and_exact_decimal_json() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        response = client.get("/features/btcusdt/latest")
        assert response.status_code == 200
        snapshot = response.json()
        FeatureSnapshot.model_validate(snapshot)
        assert snapshot["state"] == "ready"
        assert snapshot["closed_candles"] == 3
        assert all(snapshot[name]["state"] == "ready" for name in GROUPS)
        assert snapshot["trade"]["values"]["price"] == "12345.123456789012345678"
        assert snapshot["trade"]["values"]["quantity"] == "0.001"
        assert snapshot["returns"]["values"]["close"] == "16"
        assert snapshot["trend"]["values"]["ema_long"] == "14"
        assert snapshot["microstructure"]["values"]["spread_bps"] == "200.00"
        assert snapshot["mark_funding"]["values"]["funding_rate"] == "-0.0001"
        assert "NaN" not in response.text and "Infinity" not in response.text
        assert client.get("/market/BTCUSDT/latest").json()["events"]["kline:1m"]["close"] == "999"
        status = client.get("/features/status").json()
        assert status["running"] is True
        assert status["symbols"][0]["state"] == "ready"
        assert client.get("/market/status").json()["subscriber_count"] == 1
        # No depth observation was published: it cannot invalidate independent features.
        assert client.get("/market/BTCUSDT/latest").json()["streams"]["depth"]["reason"] == "missing"


def test_partial_feature_api_distinguishes_default_warmup_from_ready_context() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(), source=source)
    with TestClient(application) as client:
        wait_for_source(client, source)
        snapshot = client.get("/features/BTCUSDT/latest").json()
        assert snapshot["state"] == "partial"
        for name in CANDLE_GROUPS:
            assert snapshot[name]["state"] == "warming_up"
            assert snapshot[name]["values"] is None
            assert "insufficient_history" in snapshot[name]["reasons"]
        assert snapshot["trend"]["required_samples"] == 50
        assert snapshot["trend"]["available_samples"] == 3
        for name in ("trade", "microstructure", "mark_funding"):
            assert snapshot[name]["state"] == "ready"


def test_stale_book_only_nulls_microstructure_in_api() -> None:
    source = FeatureSource(book_age=60)
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        snapshot = client.get("/features/BTCUSDT/latest").json()
        assert snapshot["state"] == "partial"
        assert snapshot["microstructure"]["state"] == "stale"
        assert snapshot["microstructure"]["values"] is None
        assert snapshot["microstructure"]["reasons"] == ["book_ticker:event_stale"]
        assert all(snapshot[name]["state"] == "ready" for name in GROUPS if name != "microstructure")


def test_failed_source_makes_feature_sources_stale_with_safe_diagnostics() -> None:
    source = FeatureSource(fail=True)
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        response = client.get("/features/BTCUSDT/latest")
        snapshot = response.json()
        assert snapshot["state"] == "stale"
        assert all(snapshot[name]["state"] == "stale" for name in GROUPS)
        assert all(snapshot[name]["values"] is None for name in GROUPS)
        assert "non-sensitive-feature-source-error-marker" not in response.text
        assert "RuntimeError" not in response.text
        assert client.get("/market/status").json()["connections"][0]["reason"] == "source_failed"
        assert client.get("/health").json() == {"status": "ok"}


def test_lifespan_cancels_both_tasks_and_removes_feature_subscription() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(), source=source, feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        feature_task = application.state.feature_engine_task
        feed_task = application.state.market_data_task
        assert feature_task.get_loop() is feed_task.get_loop() is source.loop
        assert client.get("/features/BTCUSDT/latest").json()["closed_candles"] == 3
    assert source.closed
    assert feature_task.cancelled() and feed_task.cancelled()
    assert not application.state.feature_engine.running
    assert application.state.market_data_hub.status().subscriber_count == 0
    assert application.state.feature_engine.latest("BTCUSDT").closed_candles == 0


def test_feature_settings_are_read_at_startup_and_engine_is_new_each_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(settings=MarketDataSettings(enabled=False))
    monkeypatch.setenv("FEATURE_EMA_LONG", "60")
    monkeypatch.setenv("FEATURE_HISTORY_LIMIT", "600")
    with TestClient(application) as client:
        first_engine = application.state.feature_engine
        assert client.get("/features/status").json()["history_limit"] == 600
        assert client.get("/features/BTCUSDT/latest").json()["trend"]["required_samples"] == 60
    with TestClient(application) as client:
        assert application.state.feature_engine is not first_engine
        assert client.get("/features/BTCUSDT/latest").json()["closed_candles"] == 0


def test_injected_source_starts_consumer_even_when_network_feed_is_disabled() -> None:
    source = FeatureSource()
    application = create_app(settings=feed_settings(enabled=False), source=source,
                             feature_settings=small_settings())
    with TestClient(application) as client:
        wait_for_source(client, source)
        assert client.get("/features/status").json()["running"] is True
        assert client.get("/features/BTCUSDT/latest").json()["state"] == "ready"


def test_application_factory_does_not_construct_network_or_feature_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Runtime should be constructed only during lifespan")

    monkeypatch.setattr("src.main.BinancePublicMarketData", unexpected)
    monkeypatch.setattr("src.main.FeatureEngine", unexpected)
    application = create_app()
    assert not hasattr(application.state, "feature_engine")
    assert not hasattr(application.state, "market_data_task")
