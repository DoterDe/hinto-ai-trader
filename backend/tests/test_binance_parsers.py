"""Deterministic synthetic public fixtures based on the official Binance schemas."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any

import pytest

from src.domain.market_data import (
    BookTickerEvent,
    DepthEvent,
    KlineEvent,
    MarkPriceEvent,
    TradeEvent,
)
from src.infrastructure.binance.parsers import MarketDataParseError, parse_message


EVENT_MS = 1_788_739_200_123
RECEIVED_AT = datetime(2026, 9, 6, 12, 0, 1, tzinfo=timezone.utc)
EVENT_AT = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=EVENT_MS)
PAYLOADS: dict[str, dict[str, Any]] = {
    "trade": {
        "e": "aggTrade", "E": EVENT_MS, "s": "BTCUSDT", "a": 501,
        "p": "60000.123456789012345678", "q": "0.125", "nq": "0.100",
        "f": 100, "l": 103, "T": EVENT_MS - 2, "m": True, "st": 1,
    },
    "kline": {
        "e": "kline", "E": EVENT_MS, "s": "BTCUSDT",
        "k": {
            "t": EVENT_MS - 123, "T": EVENT_MS + 59_876, "s": "BTCUSDT",
            "i": "1m", "f": 100, "L": 200,
            "o": "60000.00", "c": "60100.00", "h": "60200.00", "l": "59900.00",
            "v": "2.5", "n": 101, "x": False, "q": "150000.00",
            "V": "1.2", "Q": "72000.00", "B": "0",
        },
    },
    "book_ticker": {
        "e": "bookTicker", "E": EVENT_MS, "T": EVENT_MS - 2, "s": "BTCUSDT",
        "u": 900, "b": "60000.10", "B": "0.2", "a": "60000.20", "A": "0.3",
        "st": 1, "ps": "BTCUSDT",
    },
    "mark_price": {
        "e": "markPriceUpdate", "E": EVENT_MS, "s": "BTCUSDT",
        "p": "60000.15", "i": "59990.00", "P": "59995.00", "r": "-0.0001",
        "T": EVENT_MS + 3_600_000, "ap": "60000.10", "st": 1,
    },
    "depth": {
        "e": "depthUpdate", "E": EVENT_MS, "T": EVENT_MS - 2, "s": "BTCUSDT",
        "U": 901, "u": 905, "pu": 900,
        "b": [["60000.10", "0.0"], ["59999.00", "3.2"]],
        "a": [["60000.20", "0.7"]], "st": 1, "ps": "BTCUSDT",
    },
}
STREAMS = {
    "trade": "btcusdt@aggTrade",
    "kline": "btcusdt@kline_1m",
    "book_ticker": "btcusdt@bookTicker",
    "mark_price": "btcusdt@markPrice@1s",
    "depth": "btcusdt@depth",
}
EVENT_CLASSES = {
    "trade": TradeEvent,
    "kline": KlineEvent,
    "book_ticker": BookTickerEvent,
    "mark_price": MarkPriceEvent,
    "depth": DepthEvent,
}


def encode(kind: str, *, payload: dict[str, Any] | None = None, stream: str | None = None) -> str:
    return json.dumps({"stream": stream or STREAMS[kind], "data": payload or PAYLOADS[kind]})


@pytest.mark.parametrize("kind", PAYLOADS)
@pytest.mark.parametrize("wire_format", ["raw", "combined", "bytes"])
def test_normalizes_all_stream_types_and_wire_formats(kind: str, wire_format: str) -> None:
    message = json.dumps(PAYLOADS[kind]) if wire_format == "raw" else encode(kind)
    event = parse_message(
        message.encode() if wire_format == "bytes" else message,
        received_at=RECEIVED_AT,
    )
    assert isinstance(event, EVENT_CLASSES[kind])
    assert event.symbol == "BTCUSDT"
    assert event.event_time == EVENT_AT
    assert event.received_at == RECEIVED_AT
    assert event.event_time.tzinfo == timezone.utc
    assert "st" not in event.model_dump()
    assert "e" not in event.model_dump()


def test_trade_preserves_decimal_precision_identifiers_and_rpi_quantity() -> None:
    event = parse_message(encode("trade"), received_at=RECEIVED_AT)
    assert isinstance(event, TradeEvent)
    assert event.price == Decimal("60000.123456789012345678")
    assert event.quantity == Decimal("0.125")
    assert event.normal_quantity == Decimal("0.100")
    assert (event.aggregate_trade_id, event.first_trade_id, event.last_trade_id) == (501, 100, 103)
    assert event.buyer_is_maker is True
    assert event.trade_time == EVENT_AT - timedelta(milliseconds=2)


def test_kline_preserves_candle_bounds_ohlcv_and_closed_flag() -> None:
    event = parse_message(encode("kline"), received_at=RECEIVED_AT)
    assert isinstance(event, KlineEvent)
    assert event.interval == "1m"
    assert event.open_time == EVENT_AT - timedelta(milliseconds=123)
    assert event.close_time == EVENT_AT + timedelta(milliseconds=59_876)
    assert (event.open, event.high, event.low, event.close) == tuple(
        Decimal(value) for value in ("60000", "60200", "59900", "60100")
    )
    assert (event.volume, event.quote_volume) == (Decimal("2.5"), Decimal("150000"))
    assert (event.taker_buy_volume, event.taker_buy_quote_volume) == (Decimal("1.2"), Decimal("72000"))
    assert event.trade_count == 101
    assert event.is_closed is False


def test_book_ticker_preserves_top_prices_quantities_and_update_id() -> None:
    event = parse_message(encode("book_ticker"), received_at=RECEIVED_AT)
    assert isinstance(event, BookTickerEvent)
    assert event.update_id == 900
    assert (event.bid_price, event.ask_price) == (Decimal("60000.10"), Decimal("60000.20"))
    assert (event.bid_quantity, event.ask_quantity) == (Decimal("0.2"), Decimal("0.3"))
    assert event.transaction_time == EVENT_AT - timedelta(milliseconds=2)


def test_mark_price_uses_event_time_for_event_and_future_time_for_funding() -> None:
    event = parse_message(encode("mark_price"), received_at=RECEIVED_AT)
    assert isinstance(event, MarkPriceEvent)
    assert (event.mark_price, event.index_price) == (Decimal("60000.15"), Decimal("59990.00"))
    assert event.estimated_settle_price == Decimal("59995.00")
    assert event.funding_rate == Decimal("-0.0001")
    assert event.event_time == EVENT_AT
    assert event.next_funding_time == EVENT_AT + timedelta(hours=1)


def test_depth_preserves_absolute_quantities_zero_deletions_and_continuity_ids() -> None:
    event = parse_message(encode("depth"), received_at=RECEIVED_AT)
    assert isinstance(event, DepthEvent)
    assert (event.first_update_id, event.final_update_id, event.previous_final_update_id) == (901, 905, 900)
    assert [(level.price, level.quantity) for level in event.bids] == [
        (Decimal("60000.10"), Decimal("0")), (Decimal("59999"), Decimal("3.2"))
    ]
    assert [(level.price, level.quantity) for level in event.asks] == [(Decimal("60000.20"), Decimal("0.7"))]
    assert event.transaction_time == EVENT_AT - timedelta(milliseconds=2)


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT"])
@pytest.mark.parametrize("kind", PAYLOADS)
def test_accepts_all_eight_requested_symbols(kind: str, symbol: str) -> None:
    payload = deepcopy(PAYLOADS[kind])
    payload["s"] = symbol
    if kind == "kline":
        payload["k"]["s"] = symbol
    event = parse_message(
        encode(kind, payload=payload, stream=STREAMS[kind].replace("btcusdt", symbol.lower())),
        received_at=RECEIVED_AT,
    )
    assert event.symbol == symbol


@pytest.mark.parametrize("kind", PAYLOADS)
def test_accepts_additive_migration_fields_and_missing_symbol_type(kind: str) -> None:
    payload = deepcopy(PAYLOADS[kind])
    payload.pop("st", None)
    payload["future_exchange_field"] = {"new": [1, 2]}
    event = parse_message(encode(kind, payload=payload), received_at=RECEIVED_AT)
    assert isinstance(event, EVENT_CLASSES[kind])


@pytest.mark.parametrize("kind,field", [("trade", "nq"), ("mark_price", "P")])
def test_optional_public_fields_may_be_absent(kind: str, field: str) -> None:
    payload = deepcopy(PAYLOADS[kind])
    del payload[field]
    event = parse_message(encode(kind, payload=payload), received_at=RECEIVED_AT)
    assert getattr(event, "normal_quantity" if kind == "trade" else "estimated_settle_price") is None


@pytest.mark.parametrize("kind", PAYLOADS)
@pytest.mark.parametrize("field", ["e", "E", "s"])
def test_missing_common_required_fields_are_rejected(kind: str, field: str) -> None:
    payload = deepcopy(PAYLOADS[kind])
    del payload[field]
    with pytest.raises(MarketDataParseError):
        parse_message(encode(kind, payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("kind,field", [("trade", "q"), ("kline", "k"), ("book_ticker", "B"), ("mark_price", "T"), ("depth", "pu"), ("depth", "b"), ("depth", "a")])
def test_missing_event_specific_fields_are_rejected(kind: str, field: str) -> None:
    payload = deepcopy(PAYLOADS[kind])
    del payload[field]
    with pytest.raises(MarketDataParseError):
        parse_message(encode(kind, payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("invalid", [True, False, "1788739200123", 1788739200123.0, -1, 10**100, None])
@pytest.mark.parametrize("field", ["E", "T", "a"])
def test_millisecond_timestamps_and_identifiers_require_bounded_nonnegative_integers(field: str, invalid: Any) -> None:
    payload = deepcopy(PAYLOADS["trade"])
    payload[field] = invalid
    if field == "a" and invalid == 10**100:
        # IDs are arbitrary nonnegative integers, unlike bounded datetime values.
        assert parse_message(encode("trade", payload=payload), received_at=RECEIVED_AT).aggregate_trade_id == invalid
    else:
        with pytest.raises(MarketDataParseError):
            parse_message(encode("trade", payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("invalid", [True, 1.5, 100, "NaN", "Infinity", "-Infinity", "", "1_000", " 10", "10 ", "-1", "0", None])
def test_prices_require_positive_finite_decimal_strings(invalid: Any) -> None:
    payload = deepcopy(PAYLOADS["trade"])
    payload["p"] = invalid
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade", payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("kind", ["trade", "kline"])
@pytest.mark.parametrize("invalid", [0, 1, "true", "false", None])
def test_flags_require_json_booleans(kind: str, invalid: Any) -> None:
    payload = deepcopy(PAYLOADS[kind])
    if kind == "trade":
        payload["m"] = invalid
    else:
        payload["k"]["x"] = invalid
    with pytest.raises(MarketDataParseError):
        parse_message(encode(kind, payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("invalid", [2, 0, True, "1", 1.0, None])
def test_explicit_symbol_type_must_be_usd_m_integer_one(invalid: Any) -> None:
    payload = deepcopy(PAYLOADS["trade"])
    payload["st"] = invalid
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade", payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("invalid", ["btcusdt", " BTCUSDT", "BTCUSDT ", "BTC/USDT", "", 123, None])
def test_symbol_is_a_canonical_exchange_symbol(invalid: Any) -> None:
    payload = deepcopy(PAYLOADS["trade"])
    payload["s"] = invalid
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade", payload=payload), received_at=RECEIVED_AT)


@pytest.mark.parametrize("invalid", [None, {}, ["1", "2"], [["1"]], [["1", "2", "3"]], [["1", "-2"]], [["NaN", "2"]], [[1, "2"]]])
def test_depth_requires_pairs_of_valid_price_and_quantity_strings(invalid: Any) -> None:
    payload = deepcopy(PAYLOADS["depth"])
    payload["b"] = invalid
    with pytest.raises(MarketDataParseError):
        parse_message(encode("depth", payload=payload), received_at=RECEIVED_AT)


def test_depth_can_contain_no_changes_on_either_side() -> None:
    payload = deepcopy(PAYLOADS["depth"])
    payload["a"] = payload["b"] = []
    event = parse_message(encode("depth", payload=payload), received_at=RECEIVED_AT)
    assert event.bids == event.asks == ()


@pytest.mark.parametrize("stream", ["ethusdt@aggTrade", "BTCUSDT@aggTrade", "btcusdt@bookTicker", "btcusdt@aggTrade@1s"])
def test_combined_wrapper_must_agree_with_symbol_and_event_type(stream: str) -> None:
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade", stream=stream), received_at=RECEIVED_AT)


@pytest.mark.parametrize("kind,stream", [("mark_price", "btcusdt@markPrice"), ("depth", "btcusdt@depth@100ms"), ("depth", "btcusdt@depth@500ms")])
def test_accepts_other_documented_stream_update_frequencies(kind: str, stream: str) -> None:
    assert isinstance(parse_message(encode(kind, stream=stream), received_at=RECEIVED_AT), EVENT_CLASSES[kind])


@pytest.mark.parametrize("kind,stream", [("depth", "btcusdt@depth@250ms"), ("depth", "btcusdt@depth5"), ("mark_price", "btcusdt@markPrice@3s"), ("kline", "btcusdt@kline_5m")])
def test_rejects_wrong_stream_subtypes_and_candle_interval_mismatch(kind: str, stream: str) -> None:
    with pytest.raises(MarketDataParseError):
        parse_message(encode(kind, stream=stream), received_at=RECEIVED_AT)


def test_nested_candle_symbol_must_agree_with_event_symbol() -> None:
    payload = deepcopy(PAYLOADS["kline"])
    payload["k"]["s"] = "ETHUSDT"
    with pytest.raises(MarketDataParseError):
        parse_message(encode("kline", payload=payload), received_at=RECEIVED_AT)


def test_expected_streams_requires_membership_and_a_combined_wrapper() -> None:
    allowed = {STREAMS["trade"]}
    assert isinstance(parse_message(encode("trade"), received_at=RECEIVED_AT, expected_streams=allowed), TradeEvent)
    for message in (encode("book_ticker"), json.dumps(PAYLOADS["trade"])):
        with pytest.raises(MarketDataParseError):
            parse_message(message, received_at=RECEIVED_AT, expected_streams=allowed)
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade"), received_at=RECEIVED_AT, expected_streams=set())


@pytest.mark.parametrize("message", ["", "not json", "null", "[]", "1", "{}", "true", b"\xff", '{"e":"aggTrade","e":"kline"}', '{"bad":NaN}', '{"stream":42,"data":{}}', '{"stream":"btcusdt@aggTrade"}', '{"stream":"btcusdt@aggTrade","data":[]}', '{"result":null,"id":1}', '{"e":"unexpected","E":0,"s":"BTCUSDT"}'])
def test_malformed_or_unrecognized_messages_have_constant_safe_error(message: str | bytes) -> None:
    with pytest.raises(MarketDataParseError) as error:
        parse_message(message, received_at=RECEIVED_AT)
    assert str(error.value) == "Invalid public market-data message"
    assert error.value.__suppress_context__ is True


def test_parser_requires_an_aware_local_receive_timestamp() -> None:
    with pytest.raises(MarketDataParseError):
        parse_message(encode("trade"), received_at=datetime(2026, 9, 6))


def test_one_bad_message_does_not_prevent_later_parsing() -> None:
    with pytest.raises(MarketDataParseError):
        parse_message("broken", received_at=RECEIVED_AT)
    assert isinstance(parse_message(encode("trade"), received_at=RECEIVED_AT), TradeEvent)
