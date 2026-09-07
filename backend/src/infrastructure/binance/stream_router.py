from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from src.domain.market_data import EventType


DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT",
)
DEFAULT_BASE_URL = "wss://fstream.binance.com"
KLINE_INTERVALS = frozenset(
    ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
     "12h", "1d", "3d", "1w", "1M")
)


class BinanceRoute(str, Enum):
    PUBLIC = "public"
    MARKET = "market"


# Verified against Binance's routed USD-M stream catalog on 2026-09-06.
STREAM_ROUTES = {
    EventType.TRADE: BinanceRoute.MARKET,
    EventType.KLINE: BinanceRoute.MARKET,
    EventType.MARK_PRICE: BinanceRoute.MARKET,
    EventType.BOOK_TICKER: BinanceRoute.PUBLIC,
    EventType.DEPTH: BinanceRoute.PUBLIC,
}


def normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    if isinstance(symbols, str) or not symbols:
        raise ValueError("symbols must be a nonempty sequence")
    result: list[str] = []
    for value in symbols:
        if not isinstance(value, str):
            raise ValueError("invalid symbol")
        symbol = value.strip().upper()
        if re.fullmatch(r"[A-Z0-9]{3,32}", symbol) is None:
            raise ValueError("invalid symbol")
        if symbol not in result:
            result.append(symbol)
    return tuple(result)


def validate_base_url(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("invalid WebSocket base URL")
    url = urlsplit(value)
    # Local ws URLs support offline protocol tests. Public connections use TLS.
    if (
        not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or not (url.scheme == "wss" or (
            url.scheme == "ws" and url.hostname in ("localhost", "127.0.0.1", "::1")
        ))
    ):
        raise ValueError("WebSocket base must be a credential-free root WSS URL")
    try:
        url.port
    except ValueError:
        raise ValueError("invalid WebSocket port") from None
    return value.rstrip("/")


@dataclass(frozen=True)
class StreamSpec:
    name: str
    symbol: str
    event_type: EventType
    interval: str | None = None


@dataclass(frozen=True)
class RoutedConnection:
    route: BinanceRoute
    streams: tuple[StreamSpec, ...]
    url: str

    @property
    def names(self) -> frozenset[str]:
        return frozenset(stream.name for stream in self.streams)

    @property
    def event_types(self) -> tuple[EventType, ...]:
        return tuple(dict.fromkeys(stream.event_type for stream in self.streams))


def build_connections(
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    *,
    kline_intervals: Sequence[str] = ("1m",),
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[RoutedConnection, ...]:
    """Build two routed combined subscriptions; never an unrouted URL."""
    normalized = normalize_symbols(symbols)
    if isinstance(kline_intervals, str) or not kline_intervals:
        raise ValueError("at least one kline interval is required")
    if any(interval not in KLINE_INTERVALS for interval in kline_intervals):
        raise ValueError("unsupported kline interval")
    intervals = tuple(dict.fromkeys(kline_intervals))
    root = validate_base_url(base_url)
    groups: dict[BinanceRoute, list[StreamSpec]] = {route: [] for route in BinanceRoute}
    for symbol in normalized:
        lower = symbol.lower()
        specs = [
            StreamSpec(f"{lower}@aggTrade", symbol, EventType.TRADE),
            StreamSpec(f"{lower}@markPrice@1s", symbol, EventType.MARK_PRICE),
            StreamSpec(f"{lower}@bookTicker", symbol, EventType.BOOK_TICKER),
            # No @250ms suffix: the bare diff-depth stream has a 250ms default.
            StreamSpec(f"{lower}@depth", symbol, EventType.DEPTH),
            *(StreamSpec(f"{lower}@kline_{interval}", symbol, EventType.KLINE, interval)
              for interval in intervals),
        ]
        for spec in specs:
            groups[STREAM_ROUTES[spec.event_type]].append(spec)
    connections = []
    for route, specs in groups.items():
        if len(specs) > 1024:
            raise ValueError("combined connection exceeds Binance's 1024-stream limit")
        names = "/".join(spec.name for spec in specs)
        connections.append(RoutedConnection(route, tuple(specs), f"{root}/{route.value}/stream?streams={names}"))
    return tuple(connections)
