import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.application.market_data_hub import MarketDataHub, MarketStatus, SymbolMarketSnapshot
from src.domain.market_data import (
    BookTickerEvent, ConnectionStatus, DepthEvent, EventType, KlineEvent,
    MarketConnectionState, MarkPriceEvent, NormalizedMarketEvent, TradeEvent,
)


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
REGULAR = (EventType.TRADE, EventType.KLINE, EventType.MARK_PRICE)
FAST = (EventType.BOOK_TICKER, EventType.DEPTH)


def event(kind: EventType = EventType.TRADE, **updates: Any) -> NormalizedMarketEvent:
    common = dict(symbol="BTCUSDT", event_time=NOW, received_at=NOW)
    cases: dict[EventType, tuple[Any, dict[str, Any]]] = {
        EventType.TRADE: (TradeEvent, dict(aggregate_trade_id=10, first_trade_id=10,
            last_trade_id=11, price="10", quantity="2", trade_time=NOW, buyer_is_maker=False)),
        EventType.KLINE: (KlineEvent, dict(interval="1m", open_time=NOW,
            close_time=NOW + timedelta(minutes=1), open="10", high="11", low="9", close="10",
            volume="2", quote_volume="20", trade_count=2, is_closed=False,
            taker_buy_volume="1", taker_buy_quote_volume="10")),
        EventType.BOOK_TICKER: (BookTickerEvent, dict(update_id=10, bid_price="10",
            bid_quantity="1", ask_price="11", ask_quantity="1", transaction_time=NOW)),
        EventType.MARK_PRICE: (MarkPriceEvent, dict(mark_price="10", index_price="10",
            funding_rate="0.001", next_funding_time=NOW + timedelta(hours=8))),
        EventType.DEPTH: (DepthEvent, dict(first_update_id=10, final_update_id=11,
            previous_final_update_id=9, bids=[dict(price="10", quantity="2")], asks=[],
            transaction_time=NOW)),
    }
    model, fields = cases[kind]
    return model(**(common | fields | updates))


def connection(name: str, **updates: Any) -> MarketConnectionState:
    return MarketConnectionState(**(dict(
        connection_id=name, event_types=REGULAR if name == "regular" else FAST,
        status=ConnectionStatus.CONNECTED, changed_at=NOW, generation=1,
    ) | updates))


def publish(hub: MarketDataHub, value: NormalizedMarketEvent) -> None:
    hub.publish(value, connection_id="regular" if value.event_type in REGULAR else "fast")


def publish_all(hub: MarketDataHub, **updates: Any) -> None:
    for kind in EventType:
        publish(hub, event(kind, **updates))


@pytest.fixture
def clock() -> list[datetime]:
    return [NOW]


@pytest.fixture
def hub(clock: list[datetime]) -> MarketDataHub:
    value = MarketDataHub(["BTCUSDT", "ETHUSDT"], clock=lambda: clock[0])
    value.update_connection(connection("regular"))
    value.update_connection(connection("fast"))
    return value


def test_empty_hub_is_stale_per_symbol_and_stream(hub: MarketDataHub) -> None:
    status = hub.status()
    assert status.stale
    assert set(status.symbols) == {"BTCUSDT", "ETHUSDT"}
    btc = status.symbols["BTCUSDT"]
    assert btc.last_event_at is None
    assert set(btc.streams) == {"trade", "kline:1m", "book_ticker", "mark_price", "depth"}
    assert all(stream.stale and stream.reason == "missing" for stream in btc.streams.values())
    assert hub.latest("btcusdt").events == {}
    assert MarketStatus.model_validate_json(status.model_dump_json()) == status


def test_all_expected_streams_required_and_symbols_isolated(hub: MarketDataHub) -> None:
    publish(hub, event())
    assert hub.latest("BTCUSDT").stale
    publish_all(hub)
    btc = hub.latest("BTCUSDT")
    assert not btc.stale
    assert btc.last_event_at == btc.last_received_at == NOW
    assert len(btc.events) == 5
    assert hub.latest("ETHUSDT").stale
    assert hub.status().stale
    publish_all(hub, symbol="ETHUSDT")
    assert not hub.status().stale
    assert SymbolMarketSnapshot.model_validate_json(btc.model_dump_json()) == btc


def test_read_snapshots_do_not_expose_mutable_cache(hub: MarketDataHub) -> None:
    publish_all(hub)
    snapshot = hub.latest("BTCUSDT")
    snapshot.events.clear()
    snapshot.streams.clear()
    assert len(hub.latest("BTCUSDT").events) == 5
    assert len(hub.latest("BTCUSDT").streams) == 5


def test_freshness_expires_without_incoming_messages(hub: MarketDataHub, clock: list[datetime]) -> None:
    publish_all(hub)
    clock[0] = NOW + timedelta(seconds=9.999)
    assert not hub.latest("BTCUSDT").stale
    clock[0] = NOW + timedelta(seconds=10)
    snapshot = hub.latest("BTCUSDT")
    assert snapshot.stale
    assert all(stream.reason == "event_stale" for stream in snapshot.streams.values())
    assert snapshot.streams["trade"].event_age_seconds == 10


@pytest.mark.parametrize("field,seconds,reason", [
    ("event_time", -11, "event_stale"), ("received_at", -11, "receive_stale"),
    ("event_time", 1, "clock_skew"), ("received_at", 1, "clock_skew"),
])
def test_both_timestamp_ages_and_future_skew_are_checked(
    hub: MarketDataHub, field: str, seconds: int, reason: str,
) -> None:
    publish(hub, event(**{field: NOW + timedelta(seconds=seconds)}))
    stream = hub.latest("BTCUSDT").streams["trade"]
    assert stream.stale and stream.reason == reason


def test_clock_rollback_marks_existing_events_stale(hub: MarketDataHub, clock: list[datetime]) -> None:
    publish_all(hub)
    clock[0] = NOW - timedelta(milliseconds=1)
    assert hub.latest("BTCUSDT").streams["trade"].reason == "clock_skew"


@pytest.mark.parametrize("kind", list(EventType))
@pytest.mark.parametrize("field", ["event_time", "received_at"])
def test_future_observation_does_not_poison_ordering(
    hub: MarketDataHub, clock: list[datetime], kind: EventType, field: str,
) -> None:
    publish(hub, event(kind))
    clock[0] = NOW + timedelta(seconds=1)
    changes: dict[str, Any] = {
        "event_time": clock[0], "received_at": clock[0],
        field: NOW + timedelta(days=365),
    }
    id_fields = {
        EventType.TRADE: "aggregate_trade_id", EventType.BOOK_TICKER: "update_id",
        EventType.DEPTH: "final_update_id",
    }
    if kind in id_fields:
        changes[id_fields[kind]] = 99999
    publish(hub, event(kind, **changes))
    key = "kline:1m" if kind == EventType.KLINE else kind.value
    assert hub.latest("BTCUSDT").streams[key].reason == "clock_skew"
    clock[0] = NOW + timedelta(seconds=2)
    changes = {"event_time": clock[0], "received_at": clock[0]}
    if kind in id_fields:
        changes[id_fields[kind]] = 12
    coherent = event(kind, **changes)
    publish(hub, coherent)
    assert hub.latest("BTCUSDT").events[key] == coherent
    assert not hub.latest("BTCUSDT").streams[key].stale


def test_initial_future_event_recovers_without_waiting_for_bad_timestamp(
    hub: MarketDataHub,
) -> None:
    publish(hub, event(event_time=NOW + timedelta(days=1), aggregate_trade_id=99999))
    publish(hub, event())
    assert hub.latest("BTCUSDT").events["trade"] == event()
    assert not hub.latest("BTCUSDT").streams["trade"].stale


def test_bad_clock_observation_stays_stale_until_replaced(
    hub: MarketDataHub, clock: list[datetime],
) -> None:
    publish(hub, event(event_time=NOW + timedelta(seconds=1)))
    clock[0] = NOW + timedelta(seconds=2)
    assert hub.latest("BTCUSDT").streams["trade"].reason == "clock_skew"


def test_clock_rollback_allows_new_coherent_observation(
    hub: MarketDataHub, clock: list[datetime],
) -> None:
    publish(hub, event())
    clock[0] = NOW - timedelta(seconds=1)
    publish(hub, event(event_time=clock[0], received_at=clock[0], aggregate_trade_id=11))
    assert not hub.latest("BTCUSDT").streams["trade"].stale


@pytest.mark.parametrize("status", [ConnectionStatus.DISABLED, ConnectionStatus.CONNECTING,
    ConnectionStatus.RECONNECTING, ConnectionStatus.STOPPED])
def test_connection_loss_invalidates_only_its_streams(hub: MarketDataHub, status: ConnectionStatus) -> None:
    publish_all(hub)
    hub.update_connection(connection("regular", status=status))
    snapshot = hub.latest("BTCUSDT")
    assert snapshot.stale
    assert snapshot.streams["trade"].reason == "disconnected"
    assert not snapshot.streams["depth"].stale
    assert snapshot.events["trade"].event_time == NOW


def test_reconnect_cannot_freshen_previous_generation_or_replayed_events(
    hub: MarketDataHub, clock: list[datetime],
) -> None:
    publish_all(hub)
    clock[0] = NOW + timedelta(seconds=1)
    hub.update_connection(connection("regular", generation=2, changed_at=clock[0], last_message_at=clock[0]))
    assert hub.latest("BTCUSDT").streams["trade"].reason == "awaiting_recovery"
    publish(hub, event(received_at=clock[0]))
    assert hub.latest("BTCUSDT").streams["trade"].reason == "awaiting_recovery"
    publish(hub, event(aggregate_trade_id=11, event_time=clock[0], received_at=clock[0]))
    stream = hub.latest("BTCUSDT").streams["trade"]
    assert not stream.stale and stream.generation == 2
    assert hub.latest("BTCUSDT").stale  # Kline and mark-price still await this generation.


@pytest.mark.parametrize("kind", list(EventType))
def test_replays_never_refresh_receipt_time(hub: MarketDataHub, clock: list[datetime], kind: EventType) -> None:
    publish(hub, event(kind))
    clock[0] = NOW + timedelta(seconds=11)
    publish(hub, event(kind, received_at=clock[0]))
    key = "kline:1m" if kind == EventType.KLINE else kind.value
    assert hub.latest("BTCUSDT").events[key].received_at == NOW
    assert hub.status().ignored_events == 1


@pytest.mark.parametrize("kind,id_field", [(EventType.TRADE, "aggregate_trade_id"),
    (EventType.BOOK_TICKER, "update_id"), (EventType.DEPTH, "final_update_id")])
def test_same_millisecond_events_advance_by_sequence_id(
    hub: MarketDataHub, kind: EventType, id_field: str,
) -> None:
    first = event(kind)
    publish(hub, first)
    newer = event(kind, **{id_field: getattr(first, id_field) + 1})
    publish(hub, newer)
    assert hub.latest("BTCUSDT").events[kind.value] == newer
    publish(hub, event(kind, event_time=NOW + timedelta(seconds=1)))
    assert hub.latest("BTCUSDT").events[kind.value] == newer
    assert hub.status().ignored_events == 1


@pytest.mark.parametrize("kind", list(EventType))
def test_older_exchange_timestamp_cannot_replace_latest(hub: MarketDataHub, kind: EventType) -> None:
    publish(hub, event(kind))
    publish(hub, event(kind, event_time=NOW - timedelta(seconds=1)))
    assert hub.status().ignored_events == 1


def test_candle_cannot_regress_or_reopen(hub: MarketDataHub) -> None:
    publish(hub, event(EventType.KLINE, is_closed=True))
    for changes in [{"is_closed": False}, {"is_closed": True, "trade_count": 1},
                    {"open_time": NOW - timedelta(minutes=1)}]:
        publish(hub, event(EventType.KLINE, event_time=NOW + timedelta(seconds=1), **changes))
    assert hub.status().ignored_events == 3
    assert hub.latest("BTCUSDT").events["kline:1m"].is_closed


@pytest.mark.parametrize("changes", [{"trade_count": 3}, {"is_closed": True},
                                   {"trade_count": 3, "is_closed": True}])
def test_same_millisecond_candle_progress_is_kept_and_replay_ignored(
    hub: MarketDataHub, clock: list[datetime], changes: dict[str, Any],
) -> None:
    publish(hub, event(EventType.KLINE))
    progressed = event(EventType.KLINE, **changes)
    publish(hub, progressed)
    assert hub.latest("BTCUSDT").events["kline:1m"] == progressed
    clock[0] = NOW + timedelta(seconds=1)
    publish(hub, event(EventType.KLINE, **changes, received_at=clock[0]))
    assert hub.latest("BTCUSDT").events["kline:1m"].received_at == NOW
    publish(hub, event(EventType.KLINE, received_at=clock[0]))
    assert hub.status().ignored_events == 2


@pytest.mark.parametrize("kind,id_fields", [
    (EventType.TRADE, {"aggregate_trade_id": 1, "first_trade_id": 1, "last_trade_id": 2}),
    (EventType.BOOK_TICKER, {"update_id": 1}),
    (EventType.DEPTH, {"first_update_id": 1, "final_update_id": 2, "previous_final_update_id": 0}),
])
def test_reconnect_allows_reset_ids_only_with_later_exchange_time(
    hub: MarketDataHub, clock: list[datetime], kind: EventType, id_fields: dict[str, int],
) -> None:
    publish(hub, event(kind))
    name = "regular" if kind in REGULAR else "fast"
    clock[0] = NOW + timedelta(seconds=1)
    hub.update_connection(connection(name, generation=2, changed_at=clock[0]))
    publish(hub, event(kind, **id_fields, received_at=clock[0]))
    assert hub.latest("BTCUSDT").streams[kind.value].reason == "awaiting_recovery"
    replacement = event(kind, **id_fields, event_time=clock[0], received_at=clock[0])
    publish(hub, replacement)
    assert hub.latest("BTCUSDT").events[kind.value] == replacement
    assert not hub.latest("BTCUSDT").streams[kind.value].stale
    assert hub.latest("BTCUSDT").streams[kind.value].generation == 2


def test_multiple_kline_intervals_have_independent_freshness(clock: list[datetime]) -> None:
    hub = MarketDataHub(["BTCUSDT"], kline_intervals=("1m", "5m"), clock=lambda: clock[0])
    hub.update_connection(connection("regular"))
    hub.update_connection(connection("fast"))
    publish_all(hub)
    assert hub.latest("BTCUSDT").streams["kline:5m"].reason == "missing"
    assert hub.latest("BTCUSDT").stale
    publish(hub, event(EventType.KLINE, interval="5m"))
    assert not hub.latest("BTCUSDT").stale


def test_wrong_source_symbol_interval_or_disconnected_publication_is_ignored(hub: MarketDataHub) -> None:
    hub.publish(event(), connection_id="unknown")
    hub.publish(event(), connection_id="fast")
    publish(hub, event(symbol="SOLUSDT"))
    publish(hub, event(EventType.KLINE, interval="5m"))
    hub.update_connection(connection("regular", status=ConnectionStatus.RECONNECTING))
    publish(hub, event())
    assert not hub.latest("BTCUSDT").events
    assert hub.status().ignored_events == 5


def test_connection_updates_cannot_revert_generation_or_time(hub: MarketDataHub) -> None:
    hub.update_connection(connection("regular", generation=2))
    hub.update_connection(connection("regular", generation=1, changed_at=NOW + timedelta(seconds=1)))
    hub.update_connection(connection("regular", generation=2, changed_at=NOW - timedelta(seconds=1)))
    state = next(state for state in hub.status().connections if state.connection_id == "regular")
    assert state.generation == 2 and state.changed_at == NOW


def test_new_connection_identity_requires_new_observations(hub: MarketDataHub) -> None:
    publish_all(hub)
    hub.update_connection(connection("replacement", event_types=REGULAR))
    assert hub.latest("BTCUSDT").streams["trade"].reason == "awaiting_recovery"


def test_slow_subscribers_drop_oldest_without_blocking_and_cleanup(hub: MarketDataHub) -> None:
    with hub.subscribe(max_queue_size=1) as slow, hub.subscribe(max_queue_size=3) as fast:
        assert hub.status().subscriber_count == 2
        first = event()
        second = event(aggregate_trade_id=11)
        publish(hub, first)
        publish(hub, second)
        assert slow.qsize() == 1 and slow.get_nowait() == second
        assert fast.get_nowait() == first
        assert fast.get_nowait() == second
        assert hub.status().dropped_events == 1
    assert hub.status().subscriber_count == 0
    publish(hub, event(aggregate_trade_id=12))
    assert slow.empty() and fast.empty()


def test_subscriber_cleanup_on_exception(hub: MarketDataHub) -> None:
    with pytest.raises(RuntimeError):
        with hub.subscribe():
            raise RuntimeError("consumer stopped")
    assert hub.status().subscriber_count == 0


def test_subscriber_cleanup_on_cancellation(hub: MarketDataHub) -> None:
    async def scenario() -> None:
        async def consumer() -> None:
            with hub.subscribe() as queue:
                await queue.get()
        task = asyncio.create_task(consumer())
        await asyncio.sleep(0)
        assert hub.status().subscriber_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert hub.status().subscriber_count == 0
    asyncio.run(scenario())


def test_bad_model_instances_are_revalidated_before_publication(hub: MarketDataHub) -> None:
    with pytest.raises(ValidationError):
        publish(hub, event().model_copy(update={"price": "NaN"}))
    assert not hub.latest("BTCUSDT").events


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_stale_threshold_rejected(value: Any) -> None:
    with pytest.raises(ValueError):
        MarketDataHub(["BTCUSDT"], stale_after_seconds=value)


@pytest.mark.parametrize("values", [[], ["BTCUSDT", "btcusdt"], "BTCUSDT"])
def test_invalid_symbol_configuration_rejected(values: Any) -> None:
    with pytest.raises(ValueError):
        MarketDataHub(values)


@pytest.mark.parametrize("values", [[], ["1m", "1m"], ["0m"], "1m"])
def test_invalid_interval_configuration_rejected(values: Any) -> None:
    with pytest.raises(ValueError):
        MarketDataHub(["BTCUSDT"], kline_intervals=values)


@pytest.mark.parametrize("value", [0, -1, 1.1, True])
def test_unbounded_or_invalid_subscriptions_rejected(hub: MarketDataHub, value: Any) -> None:
    with pytest.raises(ValueError):
        with hub.subscribe(max_queue_size=value):
            pass


def test_unknown_symbol_rejected(hub: MarketDataHub) -> None:
    with pytest.raises(KeyError):
        hub.latest("SOLUSDT")


def test_naive_clock_rejected() -> None:
    hub = MarketDataHub(["BTCUSDT"], clock=lambda: NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        hub.status()
