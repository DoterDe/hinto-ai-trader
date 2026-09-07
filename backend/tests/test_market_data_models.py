from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from src.domain.market_data import (
    BookTickerEvent,
    ConnectionStatus,
    DepthEvent,
    DepthLevel,
    EventType,
    KlineEvent,
    MarketConnectionState,
    MarkPriceEvent,
    NormalizedMarketEvent,
    TradeEvent,
)


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
COMMON: dict[str, Any] = {
    "symbol": "BTCUSDT", "event_time": NOW, "received_at": NOW,
}
TRADE: dict[str, Any] = dict(
    aggregate_trade_id=10, first_trade_id=11, last_trade_id=12,
    price="12345.123456789012345678", quantity="0.001", trade_time=NOW,
    buyer_is_maker=True,
)
KLINE: dict[str, Any] = dict(
    interval="1m", open_time=NOW, close_time=NOW + timedelta(minutes=1),
    open="10", high="12", low="9", close="11", volume="2", quote_volume="20",
    trade_count=3, is_closed=False, taker_buy_volume="1", taker_buy_quote_volume="10",
)
BOOK: dict[str, Any] = dict(
    update_id=12, bid_price="10", bid_quantity="2", ask_price="11",
    ask_quantity="3", transaction_time=NOW,
)
MARK: dict[str, Any] = dict(
    mark_price="10", index_price="10", funding_rate="-0.0001",
    next_funding_time=NOW + timedelta(hours=8),
)
DEPTH: dict[str, Any] = dict(
    first_update_id=10, final_update_id=12, previous_final_update_id=9,
    bids=[dict(price="10", quantity="2")], asks=[dict(price="11", quantity="0")],
    transaction_time=NOW,
)
EVENTS = [
    (TradeEvent, TRADE, EventType.TRADE),
    (KlineEvent, KLINE, EventType.KLINE),
    (BookTickerEvent, BOOK, EventType.BOOK_TICKER),
    (MarkPriceEvent, MARK, EventType.MARK_PRICE),
    (DepthEvent, DEPTH, EventType.DEPTH),
]


@pytest.mark.parametrize("model,fields,event_type", EVENTS)
def test_events_are_immutable_and_round_trip_discriminated_json(
    model: Any, fields: dict[str, Any], event_type: EventType,
) -> None:
    event = model(**COMMON, **fields)
    assert event.event_type == event_type
    adapter = TypeAdapter(NormalizedMarketEvent)
    assert adapter.validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError, match="frozen"):
        event.symbol = "ETHUSDT"
    with pytest.raises(ValidationError):
        model(**COMMON, **fields, raw_payload={"unexpected": "field"})


@pytest.mark.parametrize("model,fields,event_type", EVENTS)
@pytest.mark.parametrize("field", ["event_time", "received_at"])
def test_common_timestamps_require_timezone(
    model: Any, fields: dict[str, Any], event_type: EventType, field: str,
) -> None:
    with pytest.raises(ValidationError):
        model(**(COMMON | {field: NOW.replace(tzinfo=None)}), **fields)


@pytest.mark.parametrize("model,fields,event_type", EVENTS)
@pytest.mark.parametrize("symbol", ["btcusdt", "", "BTC/USDT", "BTCUSDT\nINVALID"])
def test_normalized_symbols_are_uppercase_identifiers(
    model: Any, fields: dict[str, Any], event_type: EventType, symbol: str,
) -> None:
    with pytest.raises(ValidationError):
        model(**(COMMON | {"symbol": symbol}), **fields)


@pytest.mark.parametrize(
    "model,fields,field",
    [
        (TradeEvent, TRADE, "price"), (TradeEvent, TRADE, "quantity"),
        (KlineEvent, KLINE, "volume"), (BookTickerEvent, BOOK, "bid_price"),
        (BookTickerEvent, BOOK, "ask_quantity"), (MarkPriceEvent, MARK, "funding_rate"),
    ],
)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True])
def test_decimals_are_finite_and_reject_booleans(
    model: Any, fields: dict[str, Any], field: str, value: Any,
) -> None:
    with pytest.raises(ValidationError):
        model(**COMMON, **(fields | {field: value}))


def test_decimal_precision_is_preserved() -> None:
    event = TradeEvent(**COMMON, **TRADE)
    assert event.price == Decimal("12345.123456789012345678")
    assert '"12345.123456789012345678"' in event.model_dump_json()


@pytest.mark.parametrize("value", [-1, True, "10", 10.0])
@pytest.mark.parametrize(
    "model,fields,field",
    [(TradeEvent, TRADE, "aggregate_trade_id"), (KlineEvent, KLINE, "trade_count"),
     (BookTickerEvent, BOOK, "update_id"), (DepthEvent, DEPTH, "final_update_id")],
)
def test_identifiers_are_nonnegative_strict_integers(
    model: Any, fields: dict[str, Any], field: str, value: Any,
) -> None:
    with pytest.raises(ValidationError):
        model(**COMMON, **(fields | {field: value}))


@pytest.mark.parametrize(
    "model,fields,field",
    [(TradeEvent, TRADE, "buyer_is_maker"), (KlineEvent, KLINE, "is_closed")],
)
@pytest.mark.parametrize("value", ["false", 0, 1])
def test_flags_are_strict_booleans(
    model: Any, fields: dict[str, Any], field: str, value: Any,
) -> None:
    with pytest.raises(ValidationError):
        model(**COMMON, **(fields | {field: value}))


def test_depth_zero_quantity_is_a_removal_and_lists_are_detached() -> None:
    levels = [dict(price="10", quantity="0")]
    event = DepthEvent(**COMMON, **(DEPTH | {"bids": levels}))
    levels.append(dict(price="11", quantity="5"))
    assert event.bids == (DepthLevel(price="10", quantity="0"),)
    with pytest.raises(ValidationError):
        DepthLevel(price="0", quantity="1")
    with pytest.raises(ValidationError):
        DepthLevel(price="1", quantity="-1")


def test_zero_volume_and_book_quantity_are_valid() -> None:
    assert KlineEvent(**COMMON, **(KLINE | {"volume": "0"})).volume == 0
    assert BookTickerEvent(**COMMON, **(BOOK | {"bid_quantity": "0"})).bid_quantity == 0
    assert TradeEvent(**COMMON, **TRADE, normal_quantity="0").normal_quantity == 0
    assert MarkPriceEvent(**COMMON, **MARK, estimated_settle_price="0").estimated_settle_price == 0
    with pytest.raises(ValidationError):
        TradeEvent(**COMMON, **(TRADE | {"quantity": "0"}))


def test_ranges_and_aware_supplementary_timestamps() -> None:
    with pytest.raises(ValidationError):
        TradeEvent(**COMMON, **(TRADE | {"first_trade_id": 13}))
    with pytest.raises(ValidationError):
        DepthEvent(**COMMON, **(DEPTH | {"first_update_id": 13}))
    with pytest.raises(ValidationError):
        KlineEvent(**COMMON, **(KLINE | {"close_time": NOW - timedelta(seconds=1)}))
    with pytest.raises(ValidationError):
        MarkPriceEvent(**COMMON, **(MARK | {"next_funding_time": NOW.replace(tzinfo=None)}))


def test_connection_state_has_safe_codes_and_immutable_event_types() -> None:
    event_types = [EventType.TRADE, EventType.KLINE]
    values = dict(connection_id="market", event_types=event_types,
                  status=ConnectionStatus.CONNECTED, changed_at=NOW, generation=1)
    state = MarketConnectionState(**values)
    event_types.clear()
    assert state.event_types == (EventType.TRADE, EventType.KLINE)
    for update in [{"reason": "Exception: internal connection details"},
                   {"generation": True}, {"reconnect_attempt": -1},
                   {"changed_at": NOW.replace(tzinfo=None)}]:
        with pytest.raises(ValidationError):
            MarketConnectionState(**(values | update))
    assert MarketConnectionState(**values, reason="receive_timeout").reason == "receive_timeout"
