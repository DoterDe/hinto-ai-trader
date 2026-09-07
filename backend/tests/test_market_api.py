from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.domain.market_data import (
    BookTickerEvent,
    ConnectionStatus,
    DepthEvent,
    EventType,
    KlineEvent,
    MarketConnectionState,
    MarketDataSink,
    MarkPriceEvent,
    TradeEvent,
)
from src.infrastructure.binance.settings import MarketDataSettings
from src.infrastructure.binance.stream_router import DEFAULT_SYMBOLS
from src.main import create_app


class FakeSource:
    """An exchange-independent source with deterministic data and cancellation."""

    def __init__(self, *, event_age_seconds: float = 0) -> None:
        self.event_age_seconds = event_age_seconds
        self.closed = False

    async def run(self, sink: MarketDataSink) -> None:
        received_at = datetime.now(timezone.utc)
        event_time = received_at - timedelta(seconds=self.event_age_seconds)
        sink.update_connection(MarketConnectionState(
            connection_id="test_feed", event_types=tuple(EventType),
            status=ConnectionStatus.CONNECTED, changed_at=received_at,
            last_message_at=received_at, generation=1,
        ))
        common = dict(symbol="BTCUSDT", event_time=event_time, received_at=received_at)
        events = (
            TradeEvent(
                **common, aggregate_trade_id=1, first_trade_id=1, last_trade_id=2,
                price="12345.123456789012345678", quantity="0.001", trade_time=event_time,
                buyer_is_maker=False,
            ),
            KlineEvent(
                **common, interval="1m", open_time=event_time,
                close_time=event_time + timedelta(minutes=1), open="10", high="12",
                low="9", close="11", volume="2", quote_volume="20", trade_count=3,
                is_closed=False, taker_buy_volume="1", taker_buy_quote_volume="10",
            ),
            BookTickerEvent(
                **common, update_id=1, bid_price="10", bid_quantity="2",
                ask_price="11", ask_quantity="3", transaction_time=event_time,
            ),
            MarkPriceEvent(
                **common, mark_price="10", index_price="10", funding_rate="-0.0001",
                next_funding_time=event_time + timedelta(hours=8),
            ),
            DepthEvent(
                **common, first_update_id=1, final_update_id=2, previous_final_update_id=0,
                bids=[dict(price="10", quantity="2")], asks=[dict(price="11", quantity="0")],
                transaction_time=event_time,
            ),
        )
        for event in events:
            sink.publish(event, connection_id="test_feed")
        try:
            await asyncio.Event().wait()
        finally:
            self.closed = True


def feed_settings(**overrides: object) -> MarketDataSettings:
    return MarketDataSettings(**(dict(enabled=True, symbols=("BTCUSDT",)) | overrides))


def test_disabled_status_reports_all_eight_symbols_and_both_connections() -> None:
    application = create_app(settings=MarketDataSettings(enabled=False))
    with TestClient(application) as client:
        response = client.get("/market/status")
        assert response.status_code == 200
        status = response.json()
        assert set(status["symbols"]) == set(DEFAULT_SYMBOLS)
        assert status["stale"] is True
        assert status["stale_after_seconds"] == 10
        assert len(status["connections"]) == 2
        assert {state["status"] for state in status["connections"]} == {"disabled"}
        assert all(state["stale"] for state in status["symbols"].values())
        assert status["subscriber_count"] == status["dropped_events"] == status["ignored_events"] == 0
    assert application.state.market_data_task.done()


def test_missing_snapshot_has_explicit_freshness_and_connection_state() -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        response = client.get("/market/btcusdt/latest")
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["symbol"] == "BTCUSDT"
        assert snapshot["events"] == {}
        assert snapshot["stale"] is True
        assert snapshot["last_event_at"] is snapshot["last_received_at"] is None
        assert set(snapshot["streams"]) == {"trade", "book_ticker", "mark_price", "depth", "kline:1m"}
        assert all(stream["reason"] == "missing" for stream in snapshot["streams"].values())
        assert all(stream["connection_status"] == "disabled" for stream in snapshot["streams"].values())


@pytest.mark.parametrize("symbol", ["UNKNOWN", "invalid-symbol", "INTERNAL_DIAGNOSTIC_NOTE"])
def test_unknown_symbols_return_sanitized_404(symbol: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        response = client.get(f"/market/{symbol}/latest")
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown market symbol"}
        assert symbol not in response.text


def test_mocked_source_exposes_normalized_precise_values_and_healthy_state() -> None:
    source = FakeSource()
    application = create_app(settings=feed_settings(), source=source)
    with TestClient(application) as client:
        response = client.get("/market/BTCUSDT/latest")
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["stale"] is False
        assert snapshot["events"]["trade"]["price"] == "12345.123456789012345678"
        assert snapshot["events"]["trade"]["quantity"] == "0.001"
        assert snapshot["events"]["mark_price"]["funding_rate"] == "-0.0001"
        assert snapshot["events"]["depth"]["asks"] == [{"price": "11", "quantity": "0"}]
        assert snapshot["events"]["kline:1m"]["event_type"] == "kline"
        assert all(not stream["stale"] for stream in snapshot["streams"].values())
        assert all(stream["connection_status"] == "connected" for stream in snapshot["streams"].values())
        status = client.get("/market/status").json()
        assert status["stale"] is False
        assert status["connections"][0]["status"] == "connected"
    assert source.closed
    assert application.state.market_data_task.cancelled()
    assert application.state.market_data_hub.status().connections[0].status == ConnectionStatus.STOPPED


def test_old_exchange_events_are_stale_even_when_just_received() -> None:
    application = create_app(settings=feed_settings(), source=FakeSource(event_age_seconds=60))
    with TestClient(application) as client:
        snapshot = client.get("/market/BTCUSDT/latest").json()
        assert snapshot["stale"] is True
        assert all(stream["reason"] == "event_stale" for stream in snapshot["streams"].values())
        assert all(stream["connection_status"] == "connected" for stream in snapshot["streams"].values())


def test_reconnected_snapshot_keeps_values_stale_until_each_stream_recovers() -> None:
    application = create_app(settings=feed_settings(), source=FakeSource())
    with TestClient(application) as client:
        hub = application.state.market_data_hub
        now = datetime.now(timezone.utc)
        assert client.portal is not None
        client.portal.call(hub.update_connection, MarketConnectionState(
            connection_id="test_feed", event_types=tuple(EventType),
            status=ConnectionStatus.CONNECTED, changed_at=now, generation=2,
        ))
        snapshot = client.get("/market/BTCUSDT/latest").json()
        assert snapshot["stale"] is True
        assert snapshot["events"]["trade"]["aggregate_trade_id"] == 1
        assert all(stream["reason"] == "awaiting_recovery" for stream in snapshot["streams"].values())


@pytest.mark.parametrize("report_state", [False, True])
def test_unexpected_source_failure_is_sanitized_and_reported(report_state: bool) -> None:
    class FailingSource:
        async def run(self, sink: MarketDataSink) -> None:
            if report_state:
                sink.update_connection(MarketConnectionState(
                    connection_id="test_feed", event_types=tuple(EventType),
                    status=ConnectionStatus.CONNECTING, changed_at=datetime.now(timezone.utc),
                ))
            raise RuntimeError("non-sensitive-internal-error-marker")

    application = create_app(settings=feed_settings(), source=FailingSource())
    with TestClient(application) as client:
        response = client.get("/market/status")
        assert response.status_code == 200
        assert "non-sensitive-internal-error-marker" not in response.text
        assert "RuntimeError" not in response.text
        status = response.json()
        assert status["stale"] is True
        assert status["connections"][0]["status"] == "stopped"
        assert status["connections"][0]["reason"] == "source_failed"
        assert client.get("/health").json() == {"status": "ok"}
    assert application.state.market_data_task.done()
    assert application.state.market_data_task.exception() is None


def test_unexpected_normal_source_exit_reports_stopped() -> None:
    class ReturningSource:
        async def run(self, sink: MarketDataSink) -> None:
            return

    with TestClient(create_app(settings=feed_settings(), source=ReturningSource())) as client:
        state = client.get("/market/status").json()["connections"][0]
        assert state["status"] == "stopped"
        assert state["reason"] == "source_stopped"


def test_settings_are_read_at_startup_and_hub_is_new_per_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    application = create_app()
    monkeypatch.setenv("BINANCE_MARKET_DATA_SYMBOLS", '["ETHUSDT"]')
    monkeypatch.setenv("BINANCE_MARKET_DATA_KLINE_INTERVAL", "5m")
    monkeypatch.setenv("BINANCE_MARKET_DATA_STALE_AFTER_SECONDS", "25")
    with TestClient(application) as client:
        first_hub = application.state.market_data_hub
        status = client.get("/market/status").json()
        assert set(status["symbols"]) == {"ETHUSDT"}
        assert status["stale_after_seconds"] == 25
        assert "kline:5m" in status["symbols"]["ETHUSDT"]["streams"]
    with TestClient(application) as client:
        assert application.state.market_data_hub is not first_hub
        assert client.get("/market/ETHUSDT/latest").json()["events"] == {}


@pytest.mark.parametrize("path", ["/market/status", "/market/BTCUSDT/latest"])
def test_market_routes_are_read_only(path: str) -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        assert client.post(path, json={}).status_code == 405
        assert client.delete(path).status_code == 405


def test_openapi_describes_market_response_models() -> None:
    with TestClient(create_app(settings=MarketDataSettings(enabled=False))) as client:
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/market/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/MarketStatus",
        }
        assert "SymbolMarketSnapshot" in schema["components"]["schemas"]


def test_market_routes_before_lifespan_return_service_unavailable() -> None:
    client = TestClient(create_app(settings=MarketDataSettings(enabled=False)))
    try:
        response = client.get("/market/status")
        assert response.status_code == 503
        assert response.json() == {"detail": "Market data is not initialized"}
    finally:
        client.close()
