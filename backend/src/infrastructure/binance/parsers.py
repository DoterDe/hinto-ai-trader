"""Normalize Binance public futures messages before application delivery.

Contract references (verified 2026-09-06):
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.domain.market_data import (
    BookTickerEvent,
    DepthEvent,
    DepthLevel,
    KlineEvent,
    MarkPriceEvent,
    NormalizedMarketEvent,
    TradeEvent,
)


_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{3,32}\Z")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SAFE_ERROR = "Invalid public market-data message"


class MarketDataParseError(ValueError):
    """A rejected message; its text never contains upstream payload details."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _timestamp(value: Any) -> datetime:
    # Integer arithmetic preserves millisecond precision without float rounding.
    return _EPOCH + timedelta(milliseconds=_integer(value))


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError
    return result


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError
    return value


def _levels(value: Any) -> tuple[DepthLevel, ...]:
    if not isinstance(value, list):
        raise ValueError
    levels = []
    for level in value:
        if not isinstance(level, list) or len(level) != 2:
            raise ValueError
        levels.append(DepthLevel(price=_decimal(level[0]), quantity=_decimal(level[1])))
    return tuple(levels)


def _stream_names(payload: dict[str, Any]) -> tuple[str, ...]:
    symbol = payload["s"].lower()
    match payload["e"]:
        case "aggTrade":
            return (f"{symbol}@aggTrade",)
        case "bookTicker":
            return (f"{symbol}@bookTicker",)
        case "kline":
            return (f"{symbol}@kline_{payload['k']['i']}",)
        case "markPriceUpdate":
            return (f"{symbol}@markPrice", f"{symbol}@markPrice@1s")
        case "depthUpdate":
            return tuple(f"{symbol}@depth{suffix}" for suffix in ("", "@100ms", "@500ms"))
        case _:
            raise ValueError


def _normalize(payload: dict[str, Any], received_at: datetime) -> NormalizedMarketEvent:
    symbol = payload["s"]
    if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
        raise ValueError
    # After the CM migration, public feeds may identify UM/CM explicitly.
    # The adapter is USD-M only; unknown additive fields remain harmless.
    if "st" in payload and (type(payload["st"]) is not int or payload["st"] != 1):
        raise ValueError
    common = {
        "symbol": symbol,
        "event_time": _timestamp(payload["E"]),
        "received_at": received_at,
    }
    match payload["e"]:
        case "aggTrade":
            return TradeEvent(
                **common,
                aggregate_trade_id=_integer(payload["a"]),
                first_trade_id=_integer(payload["f"]),
                last_trade_id=_integer(payload["l"]),
                price=_decimal(payload["p"]),
                quantity=_decimal(payload["q"]),
                normal_quantity=_decimal(payload["nq"]) if "nq" in payload else None,
                trade_time=_timestamp(payload["T"]),
                buyer_is_maker=_boolean(payload["m"]),
            )
        case "kline":
            candle = payload["k"]
            if not isinstance(candle, dict) or candle["s"] != symbol:
                raise ValueError
            return KlineEvent(
                **common,
                interval=candle["i"],
                open_time=_timestamp(candle["t"]),
                close_time=_timestamp(candle["T"]),
                open=_decimal(candle["o"]),
                high=_decimal(candle["h"]),
                low=_decimal(candle["l"]),
                close=_decimal(candle["c"]),
                volume=_decimal(candle["v"]),
                quote_volume=_decimal(candle["q"]),
                taker_buy_volume=_decimal(candle["V"]),
                taker_buy_quote_volume=_decimal(candle["Q"]),
                trade_count=_integer(candle["n"]),
                is_closed=_boolean(candle["x"]),
            )
        case "bookTicker":
            return BookTickerEvent(
                **common,
                update_id=_integer(payload["u"]),
                bid_price=_decimal(payload["b"]),
                bid_quantity=_decimal(payload["B"]),
                ask_price=_decimal(payload["a"]),
                ask_quantity=_decimal(payload["A"]),
                transaction_time=_timestamp(payload["T"]),
            )
        case "markPriceUpdate":
            return MarkPriceEvent(
                **common,
                mark_price=_decimal(payload["p"]),
                index_price=_decimal(payload["i"]),
                estimated_settle_price=_decimal(payload["P"]) if "P" in payload else None,
                funding_rate=_decimal(payload["r"]),
                next_funding_time=_timestamp(payload["T"]),
            )
        case "depthUpdate":
            return DepthEvent(
                **common,
                first_update_id=_integer(payload["U"]),
                final_update_id=_integer(payload["u"]),
                previous_final_update_id=_integer(payload["pu"]),
                bids=_levels(payload["b"]),
                asks=_levels(payload["a"]),
                transaction_time=_timestamp(payload["T"]),
            )
        case _:
            raise ValueError


def parse_message(
    message: str | bytes,
    *,
    received_at: datetime,
    expected_streams: Collection[str] | None = None,
) -> NormalizedMarketEvent:
    """Parse a raw event or combined envelope, rejecting malformed data safely.

    Depth events remain deltas with absolute quantities at changed price levels;
    they are never presented as an initialized or reconciled local order book.
    The network adapter supplies its expected streams to bind combined messages
    to that connection's subscriptions. Raw events are accepted only without it.
    """
    try:
        if not isinstance(message, (str, bytes)):
            raise ValueError
        if not isinstance(received_at, datetime) or received_at.utcoffset() is None:
            raise ValueError
        document = json.loads(
            message, object_pairs_hook=_object, parse_constant=_reject_constant
        )
        if not isinstance(document, dict):
            raise ValueError
        payload = document
        if "stream" in document:
            payload = document["data"]
            if not isinstance(document["stream"], str) or not isinstance(payload, dict):
                raise ValueError
        if expected_streams is not None and (
            "stream" not in document or document["stream"] not in expected_streams
        ):
            raise ValueError
        event = _normalize(payload, received_at)
        if "stream" in document and document["stream"] not in _stream_names(payload):
            raise ValueError
        return event
    except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation, RecursionError):
        raise MarketDataParseError(_SAFE_ERROR) from None
