import asyncio
from datetime import timedelta

import pytest

from src.application.market_data_hub import MarketDataHub
from test_market_data_hub import NOW, connection, event, publish


def test_subscriber_counters_are_independent_and_queue_api_is_compatible() -> None:
    hub = MarketDataHub(["BTCUSDT"])
    hub.update_connection(connection("regular"))
    with hub.subscribe(1) as slow, hub.subscribe(3) as fast:
        assert isinstance(slow, asyncio.Queue)
        publish(hub, event())
        publish(hub, event(aggregate_trade_id=11))
        assert slow.dropped_events == 1
        assert fast.dropped_events == 0
        assert hub.status().dropped_events == 1
        assert slow.get_nowait().aggregate_trade_id == 11
        slow.task_done()
        assert fast.get_nowait().aggregate_trade_id == 10
        fast.task_done()
        assert fast.get_nowait().aggregate_trade_id == 11
        fast.task_done()
        with pytest.raises(AttributeError):
            slow.dropped_events = 0
        asyncio.run(slow.join())
        asyncio.run(fast.join())
    assert hub.status().subscriber_count == 0


@pytest.mark.parametrize("field", ["event_time", "received_at"])
def test_future_diagnostics_cannot_age_into_queued_history(field: str) -> None:
    clock = [NOW]
    hub = MarketDataHub(["BTCUSDT"], clock=lambda: clock[0])
    hub.update_connection(connection("regular"))
    with hub.subscribe() as queue:
        publish(hub, event(**{field: NOW + timedelta(seconds=1)}))
        assert queue.empty()
        assert hub.latest("BTCUSDT").streams["trade"].reason == "clock_skew"
        clock[0] += timedelta(seconds=2)
        assert queue.empty()
        assert hub.latest("BTCUSDT").streams["trade"].reason == "clock_skew"
        publish(hub, event(event_time=clock[0], received_at=clock[0]))
        assert queue.qsize() == 1
        assert not hub.latest("BTCUSDT").streams["trade"].stale
