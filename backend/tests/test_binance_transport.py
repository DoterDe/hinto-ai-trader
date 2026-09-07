"""Offline lifecycle tests with controllable sockets, clocks, and retry waits."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from urllib.parse import urlsplit

import pytest
from websockets.frames import Opcode
from websockets.protocol import Protocol, Side

from src.application.market_data_hub import MarketDataHub
from src.domain.market_data import (
    ConnectionStatus,
    MarketConnectionState,
    MarketDataSink,
    NormalizedMarketEvent,
)
from src.infrastructure.binance.public_market_data import (
    BinancePublicMarketData,
    ReconnectBackoff,
)
from src.infrastructure.binance.settings import MarketDataSettings
from src.infrastructure.binance.stream_router import DEFAULT_SYMBOLS


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.epoch = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return self.epoch + timedelta(seconds=self.seconds)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def message(clock: FakeClock, route: str = "market", *, age: float = 0) -> str:
    timestamp = int((clock.now() - timedelta(seconds=age)).timestamp() * 1000)
    if route == "market":
        stream = "btcusdt@aggTrade"
        payload = {
            "e": "aggTrade", "E": timestamp, "T": timestamp, "s": "BTCUSDT",
            "a": 12, "f": 10, "l": 11, "p": "60000.00", "q": "0.2", "m": True,
        }
    else:
        stream = "btcusdt@bookTicker"
        payload = {
            "e": "bookTicker", "E": timestamp, "T": timestamp, "s": "BTCUSDT",
            "u": 12, "b": "60000.00", "B": "0.2", "a": "60000.10", "A": "0.3",
        }
    return json.dumps({"stream": stream, "data": payload})


@dataclass
class ReceiveStep:
    value: str | bytes | Exception | Callable[[], str]
    elapsed: float = 0


class FakeSocket:
    def __init__(self, clock: FakeClock, *steps: ReceiveStep) -> None:
        self.clock = clock
        self.steps = deque(steps)
        self.incoming: asyncio.Queue[ReceiveStep] = asyncio.Queue()
        self.reading = asyncio.Event()
        self.cancelled = False
        self.received = 0

    async def recv(self) -> str | bytes:
        self.reading.set()
        if self.steps:
            step = self.steps.popleft()
        else:
            try:
                step = await self.incoming.get()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        self.clock.advance(step.elapsed)
        self.received += 1
        if isinstance(step.value, Exception):
            raise step.value
        return step.value() if callable(step.value) else step.value


class FakeConnection:
    def __init__(
        self, socket: FakeSocket, *, failure: Exception | None = None, block_connect: bool = False
    ) -> None:
        self.socket = socket
        self.failure = failure
        self.block_connect = block_connect
        self.entering = asyncio.Event()
        self.entered = False
        self.closed = False
        self.connect_cancelled = False

    async def __aenter__(self) -> FakeSocket:
        self.entering.set()
        if self.failure is not None:
            raise self.failure
        if self.block_connect:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.connect_cancelled = True
                raise
        self.entered = True
        return self.socket

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, clock: FakeClock, **plans: list[FakeConnection]) -> None:
        self.clock = clock
        self.plans = {route: deque(connections) for route, connections in plans.items()}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, uri: str, **kwargs: object) -> FakeConnection:
        route = urlsplit(uri).path.split("/")[1]
        planned = self.plans.get(route)
        connection = planned.popleft() if planned else FakeConnection(FakeSocket(self.clock))
        self.calls.append((uri, kwargs))
        self.connections.append(connection)
        return connection


class FakeSleep:
    def __init__(self, clock: FakeClock, *, immediate_count: int = 0) -> None:
        self.clock = clock
        self.immediate_count = immediate_count
        self.delays: list[float] = []
        self.cancelled = False

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if len(self.delays) <= self.immediate_count:
            self.clock.advance(delay)
            await asyncio.sleep(0)
            return
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class RecordingSink:
    def __init__(self) -> None:
        self.states: list[MarketConnectionState] = []
        self.events: list[tuple[str, NormalizedMarketEvent]] = []

    def update_connection(self, state: MarketConnectionState) -> None:
        self.states.append(state)

    def publish(self, event: NormalizedMarketEvent, *, connection_id: str) -> None:
        self.events.append((connection_id, event))

    def current(self, route: str) -> MarketConnectionState:
        return next(state for state in reversed(self.states) if state.connection_id == route)


async def eventually(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=2)


async def cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)


def source(
    clock: FakeClock,
    connector: FakeConnector,
    sleep: FakeSleep,
    **settings: Any,
) -> BinancePublicMarketData:
    defaults = {"enabled": True, "symbols": ("BTCUSDT",), "receive_timeout": 10, "rotate_after_seconds": 100}
    return BinancePublicMarketData(
        MarketDataSettings(**(defaults | settings)),
        connector=connector,
        sleep=sleep,
        monotonic=clock.monotonic,
        clock=clock.now,
        random_value=lambda: 1.0,
    )


def run_route(client: BinancePublicMarketData, sink: MarketDataSink, route: str = "market") -> asyncio.Task[None]:
    group = next(group for group in client._connections if group.route.value == route)
    return asyncio.create_task(client._run_route(group, sink))


@pytest.mark.parametrize("attempt,floor,ceiling", [(0, 1, 2), (1, 2, 4), (2, 4, 8), (3, 5, 10), (10**10, 5, 10)])
@pytest.mark.parametrize("jitter", [0.0, 0.25, 0.5, 1.0])
def test_exponential_backoff_has_bounded_jitter_at_every_attempt(attempt: int, floor: float, ceiling: float, jitter: float) -> None:
    delay = ReconnectBackoff(1, 10).delay(attempt, jitter)
    assert delay == floor + (ceiling - floor) * jitter
    assert 1 <= delay <= 10


@pytest.mark.parametrize("attempt,jitter", [(-1, 0), (0, -0.1), (0, 1.1), (0, float("nan")), (0, float("inf"))])
def test_backoff_rejects_invalid_attempts_and_jitter(attempt: int, jitter: float) -> None:
    with pytest.raises(ValueError):
        ReconnectBackoff(1, 10).delay(attempt, jitter)


def test_backoff_supports_equal_minimum_and_maximum() -> None:
    assert ReconnectBackoff(3, 3).delay(100, 0.5) == 3


@pytest.mark.asyncio
async def test_run_opens_exactly_two_routed_connections_with_protocol_limits() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock)
    sleep = FakeSleep(clock)
    sink = RecordingSink()
    client = source(clock, connector, sleep, symbols=DEFAULT_SYMBOLS)
    task = asyncio.create_task(client.run(sink))
    try:
        await eventually(lambda: len(connector.calls) == 2 and all(connection.entered for connection in connector.connections))
        public_streams = "/".join(f"{symbol.lower()}@{suffix}" for symbol in DEFAULT_SYMBOLS for suffix in ("bookTicker", "depth"))
        market_streams = "/".join(f"{symbol.lower()}@{suffix}" for symbol in DEFAULT_SYMBOLS for suffix in ("aggTrade", "markPrice@1s", "kline_1m"))
        assert {uri for uri, _ in connector.calls} == {
            f"wss://fstream.binance.com/public/stream?streams={public_streams}",
            f"wss://fstream.binance.com/market/stream?streams={market_streams}",
        }
        for _, options in connector.calls:
            assert options == {
                "open_timeout": 10.0, "close_timeout": 5.0,
                "ping_interval": None, "ping_timeout": None,
                "max_size": 1_048_576, "max_queue": 32, "proxy": None,
            }
    finally:
        await cancel(task)
    assert all(connection.closed for connection in connector.connections)
    assert {sink.current(route).status for route in ("public", "market")} == {ConnectionStatus.STOPPED}


@pytest.mark.asyncio
async def test_disabled_source_reports_disabled_and_never_connects() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock)
    sink = RecordingSink()
    await source(clock, connector, FakeSleep(clock), enabled=False).run(sink)
    assert len(sink.states) == 2
    assert all(state.status == ConnectionStatus.DISABLED for state in sink.states)
    assert connector.calls == []


@pytest.mark.asyncio
async def test_malformed_and_wrong_route_messages_do_not_stop_valid_delivery() -> None:
    clock = FakeClock()
    socket = FakeSocket(clock, ReceiveStep("not json"), ReceiveStep(message(clock, "public")), ReceiveStep(message(clock)))
    connection = FakeConnection(socket)
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    task = run_route(source(clock, connector, FakeSleep(clock)), sink)
    try:
        await eventually(lambda: len(sink.events) == 1)
        assert sink.events[0][0] == "market"
        assert sink.events[0][1].symbol == "BTCUSDT"
        assert sink.current("market").malformed_messages == 2
        assert sink.current("market").status == ConnectionStatus.CONNECTED
        assert len(connector.calls) == 1
    finally:
        await cancel(task)
    assert connection.closed


@pytest.mark.asyncio
async def test_connection_failure_retries_same_combined_url_and_preserves_safe_error() -> None:
    clock = FakeClock()
    failed = FakeConnection(FakeSocket(clock), failure=OSError("upstream diagnostic must stay internal"))
    recovered = FakeConnection(FakeSocket(clock, ReceiveStep(message(clock))))
    connector = FakeConnector(clock, market=[failed, recovered])
    sleep = FakeSleep(clock, immediate_count=1)
    sink = RecordingSink()
    task = run_route(source(clock, connector, sleep), sink)
    try:
        await eventually(lambda: len(sink.events) == 1)
        assert len(connector.calls) == 2
        assert connector.calls[0][0] == connector.calls[1][0]
        assert sleep.delays == [2.0]
        reconnect = next(state for state in sink.states if state.status == ConnectionStatus.RECONNECTING)
        assert reconnect.reason == "connection_error"
        assert reconnect.reconnect_attempt == 1
        assert all("upstream diagnostic" not in state.model_dump_json() for state in sink.states)
        assert sink.current("market").generation == 1
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_each_reconnection_increments_generation_before_new_data() -> None:
    clock = FakeClock()
    first = FakeConnection(FakeSocket(clock, ReceiveStep(message(clock)), ReceiveStep(OSError())))
    second = FakeConnection(FakeSocket(clock))
    connector = FakeConnector(clock, market=[first, second])
    sink = RecordingSink()
    task = run_route(source(clock, connector, FakeSleep(clock, immediate_count=1)), sink)
    try:
        await eventually(lambda: second.entered)
        connected = [state for state in sink.states if state.status == ConnectionStatus.CONNECTED]
        assert {state.generation for state in connected} == {1, 2}
        assert sink.current("market").generation == 2
        assert sink.current("market").last_message_at is None
        assert len(sink.events) == 1
        assert first.closed
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_hub_retains_pre_reconnect_data_as_stale_until_new_generation_delivers() -> None:
    clock = FakeClock()
    first = FakeConnection(FakeSocket(clock, ReceiveStep(message(clock)), ReceiveStep(OSError())))
    second = FakeConnection(FakeSocket(clock))
    connector = FakeConnector(clock, market=[first, second])
    hub = MarketDataHub(("BTCUSDT",), clock=clock.now)
    task = run_route(source(clock, connector, FakeSleep(clock, immediate_count=1)), hub)
    try:
        await eventually(lambda: second.entered)
        snapshot = hub.latest("BTCUSDT")
        assert snapshot.events["trade"].aggregate_trade_id == 12
        assert snapshot.streams["trade"].stale
        assert snapshot.streams["trade"].reason == "awaiting_recovery"
        assert snapshot.streams["trade"].generation == 1
        assert hub.status().connections[0].generation == 2
        recovered = json.loads(message(clock))
        recovered["data"]["a"] = 13
        second.socket.incoming.put_nowait(ReceiveStep(json.dumps(recovered)))
        await eventually(lambda: hub.latest("BTCUSDT").streams["trade"].generation == 2)
        assert not hub.latest("BTCUSDT").streams["trade"].stale
        assert hub.latest("BTCUSDT").events["trade"].aggregate_trade_id == 13
    finally:
        await cancel(task)
    assert hub.latest("BTCUSDT").streams["trade"].reason == "disconnected"


@pytest.mark.asyncio
async def test_route_failure_does_not_cancel_other_connection() -> None:
    clock = FakeClock()
    bad = FakeConnection(FakeSocket(clock), failure=OSError())
    good = FakeConnection(FakeSocket(clock, ReceiveStep(message(clock, "public"))))
    connector = FakeConnector(clock, market=[bad], public=[good])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = asyncio.create_task(source(clock, connector, sleep).run(sink))
    try:
        await eventually(lambda: bool(sleep.delays) and len(sink.events) == 1)
        assert sink.current("market").status == ConnectionStatus.RECONNECTING
        assert sink.current("public").status == ConnectionStatus.CONNECTED
        assert sink.events[0][0] == "public"
        assert not good.closed
        assert not task.done()
    finally:
        await cancel(task)
    assert good.closed


@pytest.mark.asyncio
async def test_idle_read_timeout_closes_socket_and_requests_retry() -> None:
    clock = FakeClock()
    connection = FakeConnection(FakeSocket(clock))
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep, receive_timeout=0.01), sink)
    try:
        await eventually(lambda: bool(sleep.delays))
        assert sink.current("market").reason == "receive_timeout"
        assert connection.closed
        assert connection.socket.cancelled
    finally:
        await cancel(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["malformed", "old"])
async def test_busy_unusable_messages_cannot_postpone_stale_deadline(kind: str) -> None:
    clock = FakeClock()
    payload = "malformed" if kind == "malformed" else message(clock, age=60)
    socket = FakeSocket(clock, *(ReceiveStep(payload, elapsed=2) for _ in range(10)))
    connection = FakeConnection(socket)
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep, receive_timeout=6), sink)
    try:
        await eventually(lambda: bool(sleep.delays))
        assert sink.current("market").reason == "stale_stream"
        assert socket.received == 3
        assert connection.closed
        if kind == "malformed":
            assert sink.current("market").malformed_messages == 3
            assert sink.events == []
        else:
            assert len(sink.events) == 3
            assert all(event.event_time < event.received_at - timedelta(seconds=10) for _, event in sink.events)
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_busy_fresh_stream_rotates_before_binance_lifetime_limit() -> None:
    clock = FakeClock()
    socket = FakeSocket(clock, *(ReceiveStep(lambda: message(clock), elapsed=2) for _ in range(10)))
    connection = FakeConnection(socket)
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep, receive_timeout=30, rotate_after_seconds=6), sink)
    try:
        await eventually(lambda: bool(sleep.delays))
        assert sink.current("market").reason == "connection_rotation"
        assert socket.received == 3
        assert len(sink.events) == 3
        assert connection.closed
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_idle_stream_rotates_when_lifetime_expires_before_read_timeout() -> None:
    clock = FakeClock()
    connection = FakeConnection(FakeSocket(clock))
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep, rotate_after_seconds=0.01), sink)
    try:
        await eventually(lambda: bool(sleep.delays))
        assert sink.current("market").reason == "connection_rotation"
        assert connection.closed
        assert connection.socket.cancelled
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_handshake_only_flapping_does_not_reset_exponential_backoff() -> None:
    clock = FakeClock()
    connections = [FakeConnection(FakeSocket(clock, ReceiveStep(OSError()))) for _ in range(3)]
    connector = FakeConnector(clock, market=connections)
    sink = RecordingSink()
    sleep = FakeSleep(clock, immediate_count=2)
    task = run_route(source(clock, connector, sleep), sink)
    try:
        await eventually(lambda: len(sleep.delays) == 3)
        assert sleep.delays == [2, 4, 8]
        assert sink.current("market").generation == 3
        assert sink.current("market").reconnect_attempt == 3
        assert all(connection.closed for connection in connections)
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_brief_valid_delivery_does_not_reset_flapping_backoff() -> None:
    clock = FakeClock()
    connections = [
        FakeConnection(FakeSocket(clock, ReceiveStep(lambda: message(clock)), ReceiveStep(OSError())))
        for _ in range(3)
    ]
    connector = FakeConnector(clock, market=connections)
    sink = RecordingSink()
    sleep = FakeSleep(clock, immediate_count=2)
    task = run_route(source(clock, connector, sleep), sink)
    try:
        await eventually(lambda: len(sleep.delays) == 3)
        assert len(sink.events) == 3
        assert sleep.delays == [2, 4, 8]
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_sustained_usable_session_resets_backoff_after_repeated_failures() -> None:
    clock = FakeClock()
    connections = [
        FakeConnection(FakeSocket(clock, ReceiveStep(OSError()))),
        FakeConnection(FakeSocket(clock, ReceiveStep(OSError()))),
        FakeConnection(FakeSocket(
            clock,
            ReceiveStep(lambda: message(clock), elapsed=6),
            ReceiveStep(lambda: message(clock), elapsed=5),
            ReceiveStep(OSError()),
        )),
    ]
    connector = FakeConnector(clock, market=connections)
    sink = RecordingSink()
    sleep = FakeSleep(clock, immediate_count=2)
    task = run_route(source(clock, connector, sleep), sink)
    try:
        await eventually(lambda: len(sleep.delays) == 3)
        assert sleep.delays == [2, 4, 2]
        assert len(sink.events) == 2
        assert sink.current("market").reconnect_attempt == 1
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_handshake_timeout_reports_safe_connection_timeout() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock, market=[FakeConnection(FakeSocket(clock), failure=TimeoutError())])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep), sink)
    try:
        await eventually(lambda: bool(sleep.delays))
        assert sink.current("market").reason == "connection_timeout"
        assert sink.current("market").generation == 0
    finally:
        await cancel(task)


@pytest.mark.asyncio
async def test_run_rejects_duplicate_start_and_can_restart_after_cancellation() -> None:
    clock = FakeClock()
    connector = FakeConnector(clock)
    sink = RecordingSink()
    client = source(clock, connector, FakeSleep(clock))
    first = asyncio.create_task(client.run(sink))
    try:
        await eventually(lambda: len(connector.calls) == 2)
        with pytest.raises(RuntimeError, match="already running"):
            await client.run(sink)
    finally:
        await cancel(first)
    second = asyncio.create_task(client.run(sink))
    try:
        await eventually(lambda: len(connector.calls) == 4)
        assert not second.done()
    finally:
        await cancel(second)


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect_before_stop", [False, True])
async def test_source_restart_with_same_hub_requires_new_generation_data(
    reconnect_before_stop: bool,
) -> None:
    clock = FakeClock()
    first_steps = [ReceiveStep(message(clock))]
    if reconnect_before_stop:
        first_steps.append(ReceiveStep(OSError()))
    first_connection = FakeConnection(FakeSocket(clock, *first_steps))
    plans = [first_connection]
    if reconnect_before_stop:
        plans.append(FakeConnection(FakeSocket(clock)))
    restarted_connection = FakeConnection(FakeSocket(clock))
    plans.append(restarted_connection)
    connector = FakeConnector(clock, market=plans)
    hub = MarketDataHub(("BTCUSDT",), clock=clock.now)
    client = source(clock, connector, FakeSleep(clock, immediate_count=int(reconnect_before_stop)))
    first_run = asyncio.create_task(client.run(hub))
    prior_generation = 2 if reconnect_before_stop else 1
    try:
        await eventually(lambda: any(
            state.connection_id == "market" and state.generation == prior_generation
            and state.status == ConnectionStatus.CONNECTED
            for state in hub.status().connections
        ) and "trade" in hub.latest("BTCUSDT").events)
    finally:
        await cancel(first_run)
    clock.advance(0.1)
    second_run = asyncio.create_task(client.run(hub))
    try:
        await eventually(lambda: restarted_connection.entered)
        state = next(item for item in hub.status().connections if item.connection_id == "market")
        assert state.status == ConnectionStatus.CONNECTED
        assert state.generation == prior_generation + 1
        assert hub.latest("BTCUSDT").streams["trade"].reason == "awaiting_recovery"
        recovered = json.loads(message(clock))
        recovered["data"]["a"] = 13
        restarted_connection.socket.incoming.put_nowait(ReceiveStep(json.dumps(recovered)))
        await eventually(lambda: not hub.latest("BTCUSDT").streams["trade"].stale)
        assert hub.latest("BTCUSDT").streams["trade"].generation == prior_generation + 1
    finally:
        await cancel(second_run)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "read", "backoff"])
async def test_cancellation_cleans_up_at_each_await_stage(stage: str) -> None:
    clock = FakeClock()
    steps = [ReceiveStep(OSError())] if stage == "backoff" else []
    connection = FakeConnection(FakeSocket(clock, *steps), block_connect=stage == "connect")
    connector = FakeConnector(clock, market=[connection])
    sink = RecordingSink()
    sleep = FakeSleep(clock)
    task = run_route(source(clock, connector, sleep), sink)
    if stage == "connect":
        await connection.entering.wait()
    elif stage == "read":
        await connection.socket.reading.wait()
    else:
        await eventually(lambda: bool(sleep.delays))
    await cancel(task)
    assert sink.current("market").status == ConnectionStatus.STOPPED
    assert sink.current("market").reason == "shutdown"
    if stage == "connect":
        assert connection.connect_cancelled
        assert not connection.entered
    else:
        assert connection.closed
    if stage == "read":
        assert connection.socket.cancelled
    if stage == "backoff":
        assert sleep.cancelled


def test_installed_websocket_protocol_replies_to_server_ping_with_identical_payload() -> None:
    server = Protocol(Side.SERVER)
    client = Protocol(Side.CLIENT)
    payload = b"binance-heartbeat-fixture"
    server.send_ping(payload)
    for frame in server.data_to_send():
        client.receive_data(frame)
    responses = client.data_to_send()
    assert responses
    for frame in responses:
        server.receive_data(frame)
    replies = server.events_received()
    assert len(replies) == 1
    assert replies[0].opcode == Opcode.PONG
    assert replies[0].data == payload
