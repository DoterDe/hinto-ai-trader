import pytest
from pydantic import ValidationError

from src.domain.market_data import EventType
from src.infrastructure.binance.settings import MarketDataSettings
from src.infrastructure.binance.stream_router import (
    DEFAULT_SYMBOLS, BinanceRoute, build_connections,
)


def test_eight_symbols_use_exactly_two_explicit_routes() -> None:
    groups = {item.route: item for item in build_connections()}
    assert len(groups) == 2
    assert len(groups[BinanceRoute.MARKET].streams) == 24
    assert len(groups[BinanceRoute.PUBLIC].streams) == 16
    for symbol in DEFAULT_SYMBOLS:
        name = symbol.lower()
        assert {f"{name}@aggTrade", f"{name}@kline_1m", f"{name}@markPrice@1s"} <= groups[BinanceRoute.MARKET].names
        assert {f"{name}@bookTicker", f"{name}@depth"} <= groups[BinanceRoute.PUBLIC].names
    for route, group in groups.items():
        assert group.url.startswith(f"wss://fstream.binance.com/{route.value}/stream?streams=")
        assert len(group.names) == len(group.streams)
        assert "@250ms" not in group.url
    assert set(groups[BinanceRoute.PUBLIC].event_types) == {EventType.DEPTH, EventType.BOOK_TICKER}


def test_normalizes_symbols_and_supports_multiple_future_intervals() -> None:
    groups = build_connections((" btcusdt ", "BTCUSDT"), kline_intervals=("1m", "1M", "1m"))
    assert sum(len(group.streams) for group in groups) == 6
    assert "btcusdt@kline_1M" in groups[1].names
    assert all(spec.symbol == "BTCUSDT" for group in groups for spec in group.streams)


@pytest.mark.parametrize("symbols", [(), ("",), ("BTC/USDT",), ("BTC@depth",), ("BTC?x=1",), "BTCUSDT"])
def test_rejects_empty_or_injectable_symbols(symbols: object) -> None:
    with pytest.raises(ValueError):
        build_connections(symbols)


@pytest.mark.parametrize("intervals", [(), ("1s",), ("bogus",), ("1m/ethusdt@aggTrade",), "1m"])
def test_rejects_unsupported_intervals(intervals: object) -> None:
    with pytest.raises(ValueError):
        build_connections(kline_intervals=intervals)


@pytest.mark.parametrize("url", [
    "https://fstream.binance.com", "ws://fstream.binance.com",
    "wss://fstream.binance.com/market", "wss://fstream.binance.com?x=1",
    "wss://fstream.binance.com#fragment", "wss://name@fstream.binance.com",
    "wss://fstream.binance.com:bad",
    "wss://fstream.binance.com/\n", " wss://fstream.binance.com",
])
def test_rejects_nonroot_or_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        build_connections(base_url=url)


def test_local_websocket_url_is_available_for_offline_tests() -> None:
    assert build_connections(base_url="ws://127.0.0.1:9000/")[0].url.startswith("ws://127.0.0.1:9000/public/")


def test_enforces_per_connection_stream_limit() -> None:
    with pytest.raises(ValueError, match="1024"):
        build_connections(tuple(f"ASSET{index}USDT" for index in range(342)))


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINANCE_MARKET_DATA_ENABLED", "false")
    monkeypatch.setenv("BINANCE_MARKET_DATA_SYMBOLS", '["btcusdt", "ethusdt"]')
    monkeypatch.setenv("BINANCE_MARKET_DATA_KLINE_INTERVAL", "5m")
    settings = MarketDataSettings()
    assert not settings.enabled
    assert settings.symbols == ("BTCUSDT", "ETHUSDT")
    assert settings.kline_interval == "5m"


@pytest.mark.parametrize("overrides", [
    {"stale_after_seconds": 0}, {"receive_timeout": -1},
    {"reconnect_min_delay": 0}, {"reconnect_max_delay": float("inf")},
    {"stale_after_seconds": float("nan")}, {"open_timeout": 0}, {"close_timeout": 0},
    {"reconnect_min_delay": 10, "reconnect_max_delay": 1},
    {"rotate_after_seconds": 86400}, {"rotate_after_seconds": 0},
    {"symbols": ()}, {"kline_interval": "1s"},
])
def test_invalid_settings_fail_at_startup(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MarketDataSettings(**overrides)
