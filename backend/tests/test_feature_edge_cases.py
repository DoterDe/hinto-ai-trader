import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from src.application.feature_engine import FeatureEngine
from src.application.market_data_hub import MarketDataHub
from src.domain.features import Readiness
from src.indicators.microstructure import spread
from src.indicators.momentum import simple_return
from src.indicators.trend import ema
from test_feature_engine import START, active, bar, connection, publish_bar, ready, settings


def test_underflow_never_substitutes_zero_for_valid_mathematical_values() -> None:
    small, larger = Decimal("1e-2000000"), Decimal("2e-2000000")
    assert simple_return(larger, small) is None
    assert spread(small, larger) is None
    assert ema((small, larger), 1) is None


@pytest.mark.parametrize("field", ["event_time", "received_at"])
def test_delayed_future_diagnostic_cannot_fill_a_missing_candle(field: str) -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            publish_bar(clock, hub, engine, 0)
            bad = bar(1)
            if field == "event_time":
                bad = bad.model_copy(update={"received_at": clock[0]})
            else:
                clock[0] = bad.event_time
                bad = bad.model_copy(update={"received_at": clock[0] + timedelta(seconds=1)})
            hub.publish(bad, connection_id="market")
            assert hub.latest("BTCUSDT").streams["kline:1m"].reason == "clock_skew"
            clock[0] = bar(2).received_at
            hub.publish(bar(2), connection_id="market")
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 1
            assert result.last_history_reset == "candle_gap"
            assert result.trend.state == Readiness.WARMING_UP
    asyncio.run(scenario())


def test_clock_rollback_invalidates_future_history_and_rewarms() -> None:
    async def scenario() -> None:
        async with active() as (clock, hub, engine):
            ready(clock, hub, engine)
            clock[0] = START + timedelta(seconds=30)
            result = engine.latest("BTCUSDT")
            assert result.closed_candles == 0
            assert result.last_history_reset == "clock_rollback"
            for minute in range(3):
                result = publish_bar(clock, hub, engine, minute)
            assert result.trend.state == Readiness.READY
    asyncio.run(scenario())


def test_unexpected_consumer_failure_is_visible_and_unsubscribes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        clock = [START]
        hub = MarketDataHub(["BTCUSDT"], clock=lambda: clock[0])
        hub.update_connection(connection(START))
        engine = FeatureEngine(hub, settings())

        def fail(event: object) -> None:
            raise RuntimeError("arbitrary internal diagnostic")

        monkeypatch.setattr(engine, "_consume", fail)
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0)
        clock[0] = bar(0).received_at
        hub.publish(bar(0), connection_id="market")
        await task
        assert not engine.running
        assert hub.status().subscriber_count == 0
        result = engine.latest("BTCUSDT")
        assert result.trend.state == Readiness.UNAVAILABLE
        assert result.trend.reasons == ("engine_failed",)
        assert "arbitrary" not in result.model_dump_json()
    asyncio.run(scenario())
