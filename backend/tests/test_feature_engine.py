import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.application.feature_engine import FeatureEngine
from src.application.feature_settings import FeatureSettings
from src.application.market_data_hub import MarketDataHub
from src.domain.features import FeatureSnapshot, Readiness
from src.domain.market_data import (
    BookTickerEvent, ConnectionStatus, EventType, KlineEvent,
    MarketConnectionState, MarkPriceEvent, TradeEvent,
)


START = datetime(2026, 9, 8, tzinfo=timezone.utc)
CANDLE_GROUPS = ("returns", "trend", "momentum", "volatility", "volume", "regime")
ALL_GROUPS = ("trade", *CANDLE_GROUPS, "microstructure", "mark_funding")
MARKET_TYPES = (EventType.TRADE, EventType.KLINE, EventType.MARK_PRICE)


def settings(**updates: Any) -> FeatureSettings:
    return FeatureSettings(**(dict(
        ema_fast=1, ema_slow=2, ema_long=3, rsi_period=2, atr_period=2,
        roc_period=2, volatility_window=2, relative_volume_window=2,
        vwap_window=2, rolling_return_windows=(1, 2), history_limit=5,
    ) | updates))


def connection(now: datetime, name: str = "market", **updates: Any) -> MarketConnectionState:
    return MarketConnectionState(**(dict(
        connection_id=name, event_types=MARKET_TYPES if name == "market" else (EventType.BOOK_TICKER, EventType.DEPTH),
        status=ConnectionStatus.CONNECTED, changed_at=now, generation=1,
    ) | updates))


def bar(minute: int, **updates: Any) -> KlineEvent:
    opened = START + timedelta(minutes=minute)
    ended = opened + timedelta(minutes=1)
    close = Decimal(10 + minute * 2)
    volume = Decimal(2 + minute * 2)
    return KlineEvent(**(dict(
        symbol="BTCUSDT", event_time=ended, received_at=ended, interval="1m",
        open_time=opened, close_time=ended - timedelta(milliseconds=1),
        open=close, high=close + 1, low=close - 1, close=close,
        volume=volume, quote_volume=volume * close, trade_count=minute + 1,
        is_closed=True, taker_buy_volume=volume / 2,
        taker_buy_quote_volume=volume * close / 2,
    ) | updates))


def instant(hub: MarketDataHub, now: datetime, kind: str, **updates: Any) -> None:
    common = dict(symbol="BTCUSDT", event_time=now, received_at=now)
    if kind == "trade":
        event = TradeEvent(**(common | dict(
            aggregate_trade_id=int(now.timestamp()), first_trade_id=1, last_trade_id=1,
            price="103", quantity="2", trade_time=now, buyer_is_maker=False,
        ) | updates))
    elif kind == "book":
        event = BookTickerEvent(**(common | dict(
            update_id=int(now.timestamp()), bid_price="99", ask_price="101",
            bid_quantity="3", ask_quantity="1", transaction_time=now,
        ) | updates))
    else:
        event = MarkPriceEvent(**(common | dict(
            mark_price="102", index_price="100", funding_rate="0.0001",
            next_funding_time=now + timedelta(hours=8),
        ) | updates))
    hub.publish(event, connection_id="public" if kind == "book" else "market")


@asynccontextmanager
async def active(*, max_queue_size: int = 1000) -> AsyncIterator[tuple[list[datetime], MarketDataHub, FeatureEngine]]:
    clock = [START]
    hub = MarketDataHub(["BTCUSDT", "ETHUSDT"], clock=lambda: clock[0])
    hub.update_connection(connection(START))
    hub.update_connection(connection(START, "public"))
    engine = FeatureEngine(hub, settings(), max_queue_size=max_queue_size)
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0)
    try:
        yield clock, hub, engine
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def publish_bar(clock: list[datetime], hub: MarketDataHub, engine: FeatureEngine, minute: int, **updates: Any) -> FeatureSnapshot:
    event = bar(minute, **updates)
    clock[0] = event.received_at
    hub.publish(event, connection_id="market")
    return engine.latest("BTCUSDT")


def ready(clock: list[datetime], hub: MarketDataHub, engine: FeatureEngine) -> FeatureSnapshot:
    for minute in range(3):
        publish_bar(clock, hub, engine, minute)
    for kind in ("trade", "book", "mark"):
        instant(hub, clock[0], kind)
        engine.latest("BTCUSDT")
    return engine.latest("BTCUSDT")


def test_missing_inputs_have_explicit_unavailable_groups() -> None:
    async def scenario() -> None:
        async with active() as (_, _, engine):
            result = engine.latest("BTCUSDT")
            assert result.state == Readiness.UNAVAILABLE
            assert result.closed_candles == 0
            for name in ALL_GROUPS:
                group = getattr(result, name)
                assert group.state == Readiness.UNAVAILABLE
                assert group.values is None and group.reasons
    asyncio.run(scenario())


def test_candle_warmup_keeps_values_null_and_reports_samples() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            result = publish_bar(clock, hub, engine, 0)
            assert result.closed_candles == 1
            for name in CANDLE_GROUPS:
                group = getattr(result, name)
                assert group.state == Readiness.WARMING_UP
                assert group.available_samples == 1
                assert group.required_samples == 3
                assert group.values is None and group.reasons
    asyncio.run(scenario())


def test_all_required_features_ready_with_independent_expected_values() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            result = ready(clock, hub, engine)
            assert result.state == Readiness.READY
            assert result.closed_candles == 3
            assert all(getattr(result, name).state == Readiness.READY for name in ALL_GROUPS)
            assert result.trade.values.price == Decimal(103)
            assert result.returns.values.close == Decimal(14)
            assert result.returns.values.rolling_returns[-1].value == Decimal("0.4")
            assert result.trend.values.ema_fast == Decimal(14)
            assert result.trend.values.ema_slow == Decimal(13)
            assert result.trend.values.ema_long == Decimal(12)
            assert result.momentum.values.rsi == Decimal(100)
            assert result.momentum.values.roc_percent == Decimal(40)
            assert result.momentum.values.close_change == Decimal(2)
            assert result.volatility.values.true_range == Decimal(3)
            assert result.volatility.values.atr == Decimal("2.75")
            assert result.volume.values.rolling_vwap == Decimal("13.2")
            assert result.volume.values.relative_volume == Decimal(2)
            assert result.volume.values.taker_buy_ratio == Decimal("0.5")
            assert result.volume.values.taker_base_volume_delta_proxy == Decimal(0)
            assert result.microstructure.values.midpoint == Decimal(100)
            assert result.microstructure.values.spread == Decimal(2)
            assert result.microstructure.values.spread_bps == Decimal(200)
            assert result.microstructure.values.top_of_book_imbalance == Decimal("0.5")
            assert result.mark_funding.values.basis == Decimal(2)
            assert result.mark_funding.values.basis_percent == Decimal(2)
            assert result.mark_funding.values.basis_bps == Decimal(200)
            assert result.mark_funding.values.funding_rate == Decimal("0.0001")
            assert result.mark_funding.values.seconds_until_funding == 28800
            assert result.regime.values.directional_efficiency == Decimal(1)
            assert result.regime.values.relative_volume == Decimal(2)
            # Depth is intentionally absent and cannot invalidate these groups.
            assert hub.latest("BTCUSDT").streams["depth"].stale
            assert result.generated_at == clock[0]
            assert result.closed_candle_time == bar(2).close_time
            assert FeatureSnapshot.model_validate_json(result.model_dump_json()) == result
    asyncio.run(scenario())


@pytest.mark.parametrize("kind,group", [("trade", "trade"), ("book", "microstructure"), ("mark", "mark_funding")])
def test_instant_group_availability_is_independent(kind: str, group: str) -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            instant(hub, clock[0], kind)
            result = engine.latest("BTCUSDT")
            assert result.state == Readiness.PARTIAL
            assert getattr(result, group).state == Readiness.READY
            assert all(getattr(result, name).values is None for name in ALL_GROUPS if name != group)
    asyncio.run(scenario())


def test_stale_inputs_expire_without_new_events_and_recover_independently() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            clock[0] += timedelta(seconds=10)
            result = engine.latest("BTCUSDT")
            assert result.state == Readiness.STALE
            for name in ALL_GROUPS:
                assert getattr(result, name).state == Readiness.STALE
                assert getattr(result, name).values is None
            instant(hub, clock[0], "book")
            result = engine.latest("BTCUSDT")
            assert result.state == Readiness.PARTIAL
            assert result.microstructure.state == Readiness.READY
            assert result.trade.state == result.trend.state == result.mark_funding.state == Readiness.STALE
    asyncio.run(scenario())


def test_fresh_current_open_candle_keeps_recent_closed_history_ready() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            observed = START + timedelta(minutes=3, seconds=30)
            result = publish_bar(clock, hub, engine, 3, is_closed=False,
                                 event_time=observed, received_at=observed)
            assert result.closed_candles == 3
            assert all(getattr(result, name).state == Readiness.READY for name in CANDLE_GROUPS)
            assert result.returns.values.close == Decimal(14)
            assert result.trade.state == Readiness.STALE
    asyncio.run(scenario())


def test_repeated_old_open_updates_cannot_hide_a_missing_close_forever() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            observed = START + timedelta(minutes=4, seconds=11)
            result = publish_bar(clock, hub, engine, 3, is_closed=False,
                                 event_time=observed, received_at=observed)
            assert not hub.latest("BTCUSDT").streams["kline:1m"].stale
            for name in CANDLE_GROUPS:
                assert getattr(result, name).state == Readiness.STALE
                assert "closed_history_stale" in getattr(result, name).reasons
                assert getattr(result, name).values is None
    asyncio.run(scenario())


def test_open_candle_prices_do_not_change_closed_indicator_values() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            observed = clock[0] + timedelta(seconds=1)
            after = publish_bar(clock, hub, engine, 3, is_closed=False,
                                close="999", high="999", event_time=observed, received_at=observed)
            assert after.closed_candles == before.closed_candles
            for name in CANDLE_GROUPS:
                assert getattr(after, name).values == getattr(before, name).values
    asyncio.run(scenario())


def test_duplicate_and_out_of_order_events_do_not_extend_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            hub.publish(bar(2), connection_id="market")
            hub.publish(bar(1), connection_id="market")
            after = engine.latest("BTCUSDT")
            assert after.closed_candles == 3
            assert after.history_resets == before.history_resets
            assert after.trend.values == before.trend.values
    asyncio.run(scenario())


def test_observed_candle_gap_requires_rewarming() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            result = publish_bar(clock, hub, engine, 4)
            assert result.closed_candles == 1
            assert result.history_resets == before.history_resets + 1
            assert result.last_history_reset == "candle_gap"
            assert all(getattr(result, name).state == Readiness.WARMING_UP for name in CANDLE_GROUPS)
            publish_bar(clock, hub, engine, 5)
            result = publish_bar(clock, hub, engine, 6)
            assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_history_is_bounded_and_symbols_are_isolated() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            for minute in range(12):
                result = publish_bar(clock, hub, engine, minute)
                assert result.closed_candles <= 5
            assert result.closed_candles == 5
            assert result.trend.state == Readiness.READY
            other = engine.latest("ETHUSDT")
            assert other.closed_candles == 0
            assert other.state == Readiness.UNAVAILABLE
    asyncio.run(scenario())


def test_queue_overflow_is_detected_before_next_consumer_turn() -> None:
    async def scenario() -> None:
        async with active(max_queue_size=2) as (clock, hub, engine):
            before = ready(clock, hub, engine)
            for minute in (3, 4, 5):
                event = bar(minute)
                clock[0] = event.received_at
                hub.publish(event, connection_id="market")
            assert hub.status().dropped_events > 0
            result = engine.latest("BTCUSDT")
            assert result.closed_candles <= 1
            assert result.history_resets > before.history_resets
            assert result.trend.state == Readiness.WARMING_UP
            publish_bar(clock, hub, engine, 6)
            result = publish_bar(clock, hub, engine, 7)
            assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_other_subscriber_overflow_does_not_invalidate_engine_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            with hub.subscribe(max_queue_size=1):
                publish_bar(clock, hub, engine, 3)
                result = publish_bar(clock, hub, engine, 4)
                assert hub.status().dropped_events > 0
                assert result.history_resets == before.history_resets
                assert result.closed_candles == 5
                assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_new_connection_generation_invalidates_old_candle_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            hub.update_connection(connection(clock[0], generation=2))
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 0
            assert result.history_resets > before.history_resets
            assert result.trend.state == Readiness.STALE
            assert result.microstructure.state == Readiness.READY
            result = publish_bar(clock, hub, engine, 3)
            assert result.closed_candles == 1
            assert result.trend.state == Readiness.WARMING_UP
            assert result.trade.state == Readiness.STALE
            publish_bar(clock, hub, engine, 4)
            assert publish_bar(clock, hub, engine, 5).trend.state == Readiness.READY
    asyncio.run(scenario())


def test_reconnect_with_pending_old_generation_events_seeds_at_most_one() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            for minute in (3, 4):
                event = bar(minute)
                clock[0] = event.received_at
                hub.publish(event, connection_id="market")
            hub.update_connection(connection(clock[0], generation=2))
            event = bar(5)
            clock[0] = event.received_at
            hub.publish(event, connection_id="market")
            result = engine.latest("BTCUSDT")
            assert result.closed_candles <= 1
            assert result.trend.state == Readiness.WARMING_UP
    asyncio.run(scenario())


def test_public_connection_generation_does_not_reset_candle_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            hub.update_connection(connection(clock[0], "public", generation=2))
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == before.closed_candles
            assert result.history_resets == before.history_resets
            assert result.trend.state == Readiness.READY
            assert result.microstructure.state == Readiness.STALE
    asyncio.run(scenario())


def test_disconnect_without_generation_change_invalidates_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            hub.update_connection(connection(clock[0], status=ConnectionStatus.RECONNECTING))
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 0
            assert result.history_resets > before.history_resets
            assert result.trend.state == Readiness.STALE
    asyncio.run(scenario())


@pytest.mark.parametrize("updates", [dict(bid_quantity="0", ask_quantity="0"), dict(bid_price="102", ask_price="101")])
def test_invalid_microstructure_is_unavailable_without_affecting_mark(updates: dict[str, str]) -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            instant(hub, clock[0], "book", **updates)
            instant(hub, clock[0], "mark")
            result = engine.latest("BTCUSDT")
            assert result.microstructure.state == Readiness.UNAVAILABLE
            assert result.microstructure.values is None
            assert result.mark_funding.state == Readiness.READY
    asyncio.run(scenario())


def test_flat_prices_leave_undefined_efficiency_unavailable_only_in_regime() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            for minute in range(3):
                result = publish_bar(clock, hub, engine, minute, open="10", high="11", low="9", close="10")
            assert result.regime.state == Readiness.UNAVAILABLE
            assert result.regime.values is None
            assert result.momentum.values.rsi == Decimal(50)
            assert result.volatility.values.realized_volatility == 0.0
            assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_zero_volume_nulls_volume_group_without_hiding_price_features() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            for minute in range(3):
                result = publish_bar(clock, hub, engine, minute, volume="0", quote_volume="0",
                                     taker_buy_volume="0", taker_buy_quote_volume="0")
            assert result.volume.state == Readiness.UNAVAILABLE
            assert result.volume.values is None
            assert result.trend.state == Readiness.READY
            assert result.momentum.state == Readiness.READY
    asyncio.run(scenario())


def test_snapshots_are_deterministic_and_json_contains_only_finite_values() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            first = ready(clock, hub, engine)
            assert engine.latest("btcusdt") == first
            encoded = first.model_dump_json()
            json.loads(encoded, parse_constant=lambda value: pytest.fail(f"Nonfinite JSON constant: {value}"))
            assert "NaN" not in encoded and "Infinity" not in encoded
            assert {source.stream for source in first.sources} >= {"trade", "book_ticker", "mark_price", "kline:1m"}
            candle_source = next(source for source in first.sources if source.stream == "kline:1m")
            assert candle_source.event_time == bar(2).event_time
            assert candle_source.received_at == bar(2).received_at
            assert candle_source.generation == 1
    asyncio.run(scenario())


def test_status_summarizes_readiness_and_runtime() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            status = engine.status()
            assert status.running and engine.running
            assert status.interval == "1m"
            assert status.history_limit == 5
            assert status.generated_at == clock[0]
            symbols = {item.symbol: item for item in status.symbols}
            assert symbols["BTCUSDT"].state == Readiness.READY
            assert symbols["ETHUSDT"].state == Readiness.UNAVAILABLE
            assert {item.name for item in symbols["BTCUSDT"].groups} == set(ALL_GROUPS)
    asyncio.run(scenario())


def test_unknown_symbol_raises_key_error() -> None:
    hub = MarketDataHub(["BTCUSDT"], clock=lambda: START)
    with pytest.raises(KeyError):
        FeatureEngine(hub, settings()).latest("UNKNOWN")


def test_cancellation_removes_subscription_and_engine_can_restart() -> None:
    async def scenario() -> None:
        clock = [START]
        hub = MarketDataHub(["BTCUSDT"], clock=lambda: clock[0])
        hub.update_connection(connection(START))
        engine = FeatureEngine(hub, settings())
        assert not engine.running
        for _ in range(2):
            task = asyncio.create_task(engine.run())
            await asyncio.sleep(0)
            assert engine.running
            assert hub.status().subscriber_count == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not engine.running
            assert not engine.status().running
            assert hub.status().subscriber_count == 0
    asyncio.run(scenario())


def test_concurrent_run_is_rejected_without_removing_active_subscription() -> None:
    async def scenario() -> None:
        async with active() as (_, hub, engine):
            with pytest.raises(RuntimeError):
                await engine.run()
            assert engine.running
            assert hub.status().subscriber_count == 1
    asyncio.run(scenario())


def test_starting_after_cached_history_does_not_invent_prior_candles() -> None:
    async def scenario() -> None:
        clock = [START]
        hub = MarketDataHub(["BTCUSDT"], clock=lambda: clock[0])
        hub.update_connection(connection(START))
        for minute in range(3):
            clock[0] = bar(minute).received_at
            hub.publish(bar(minute), connection_id="market")
        engine = FeatureEngine(hub, settings())
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0)
        try:
            result = engine.latest("BTCUSDT")
            assert result.closed_candles <= 1
            assert result.trend.state == Readiness.WARMING_UP
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(scenario())


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_invalid_consumer_queue_capacity_rejected(size: Any) -> None:
    with pytest.raises(ValueError):
        FeatureEngine(MarketDataHub(["BTCUSDT"]), settings(), max_queue_size=size)


def test_feature_interval_must_be_configured_on_hub() -> None:
    with pytest.raises(ValueError):
        FeatureEngine(MarketDataHub(["BTCUSDT"]), settings(), interval="5m")


def test_consumer_accumulates_burst_history_without_api_reads() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            for minute in range(3):
                event = bar(minute)
                clock[0] = event.received_at
                hub.publish(event, connection_id="market")
            await asyncio.sleep(0)
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 3
            assert result.trend.state == Readiness.READY
            assert hub.status().dropped_events == 0
    asyncio.run(scenario())


def test_mislabeled_early_closed_candle_cannot_enter_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            observed = START + timedelta(minutes=3, seconds=10)
            result = publish_bar(clock, hub, engine, 3,
                                 event_time=observed, received_at=observed,
                                 close_time=observed - timedelta(milliseconds=1))
            assert result.closed_candles == 3
            assert result.history_resets == before.history_resets
            for name in CANDLE_GROUPS:
                assert getattr(result, name).state == Readiness.UNAVAILABLE
                assert getattr(result, name).values is None
            result = publish_bar(clock, hub, engine, 3)
            assert result.closed_candles == 4
            assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_connection_identity_change_invalidates_prior_history() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            before = ready(clock, hub, engine)
            hub.update_connection(connection(clock[0], "replacement", event_types=MARKET_TYPES))
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 0
            assert result.history_resets > before.history_resets
            assert result.trend.state == Readiness.STALE
            event = bar(3)
            clock[0] = event.received_at
            hub.publish(event, connection_id="replacement")
            assert engine.latest("BTCUSDT").closed_candles == 1
    asyncio.run(scenario())


def test_equal_event_timestamps_across_reconnect_do_not_establish_continuity() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            observed = START + timedelta(minutes=6)
            clock[0] = observed
            for minute in (3, 4):
                hub.publish(bar(minute, event_time=observed, received_at=observed), connection_id="market")
            hub.update_connection(connection(observed, generation=2))
            hub.publish(bar(5), connection_id="market")
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 1
            assert result.trend.state == Readiness.WARMING_UP
            assert next(source for source in result.sources if source.stream == "kline:1m").generation == 2
    asyncio.run(scenario())


def test_funding_countdown_tracks_evaluation_clock_and_retains_signed_past_time() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            instant(hub, clock[0], "mark", next_funding_time=clock[0] + timedelta(seconds=3))
            assert engine.latest("BTCUSDT").mark_funding.values.seconds_until_funding == 3
            clock[0] += timedelta(seconds=5)
            result = engine.latest("BTCUSDT")
            assert result.mark_funding.state == Readiness.READY
            assert result.mark_funding.values.seconds_until_funding == -2
    asyncio.run(scenario())


def test_old_receipt_timestamp_invalidates_only_required_group() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            instant(hub, clock[0], "book")
            instant(hub, clock[0], "mark", received_at=clock[0] - timedelta(seconds=10))
            result = engine.latest("BTCUSDT")
            assert result.microstructure.state == Readiness.READY
            assert result.mark_funding.state == Readiness.STALE
            assert result.mark_funding.values is None
            assert "mark_price:receive_stale" in result.mark_funding.reasons
    asyncio.run(scenario())
