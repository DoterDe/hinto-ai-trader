from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from src.domain.market_data import ConnectionStatus, MarketConnectionState, MarketDataSink
from src.infrastructure.binance.parsers import MarketDataParseError, parse_message
from src.infrastructure.binance.settings import MarketDataSettings
from src.infrastructure.binance.stream_router import RoutedConnection, build_connections


class WebSocket(Protocol):
    async def recv(self) -> str | bytes: ...


class Connector(Protocol):
    def __call__(self, uri: str, **kwargs: object) -> AbstractAsyncContextManager[WebSocket]: ...


@dataclass(frozen=True)
class ReconnectBackoff:
    minimum: float
    maximum: float

    def delay(self, attempt: int, jitter: float) -> float:
        """Equal jitter, bounded by minimum/maximum, including at the cap."""
        if attempt < 0 or not 0 <= jitter <= 1:
            raise ValueError("invalid backoff input")
        try:
            ceiling = min(self.maximum, math.ldexp(self.minimum, attempt + 1))
        except OverflowError:
            ceiling = self.maximum
        floor = max(self.minimum, ceiling / 2)
        return floor + (ceiling - floor) * jitter


@dataclass
class _Session:
    started: float
    last_usable: float
    usable_messages: int = 0


class _ReconnectRequested(Exception):
    pass


class BinancePublicMarketData:
    """Two routed public subscriptions, independent retries, no account access.

    Reopening the same combined URL restores all subscriptions. Cache continuity
    is deliberately not claimed: every successful connection has a new generation.
    """

    def __init__(
        self,
        settings: MarketDataSettings,
        *,
        connector: Connector = connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings
        self._connections = build_connections(
            settings.symbols, kline_intervals=(settings.kline_interval,),
            base_url=settings.websocket_base_url,
        )
        self._connector = connector
        self._sleep = sleep
        self._monotonic = monotonic
        self._clock = clock
        self._random = random_value
        self._backoff = ReconnectBackoff(settings.reconnect_min_delay, settings.reconnect_max_delay)
        # A stop/start on this source must not reuse a cache generation.
        self._generations = {group.route: 0 for group in self._connections}
        self._running = False

    async def run(self, sink: MarketDataSink) -> None:
        if self._running:
            raise RuntimeError("market source is already running")
        self._running = True
        try:
            if not self._settings.enabled:
                for group in self._connections:
                    sink.update_connection(self._initial_state(group, ConnectionStatus.DISABLED))
                return
            async with asyncio.TaskGroup() as tasks:
                for group in self._connections:
                    tasks.create_task(self._run_route(group, sink), name=f"binance-{group.route.value}")
        finally:
            self._running = False

    def _initial_state(self, group: RoutedConnection, status: ConnectionStatus) -> MarketConnectionState:
        return MarketConnectionState(
            connection_id=group.route.value, event_types=group.event_types,
            status=status, changed_at=self._clock(),
            generation=self._generations[group.route],
        )

    async def _run_route(self, group: RoutedConnection, sink: MarketDataSink) -> None:
        state = self._initial_state(group, ConnectionStatus.CONNECTING)
        attempt = 0
        try:
            while True:
                state = state.model_copy(update={
                    "status": ConnectionStatus.CONNECTING, "changed_at": self._clock(),
                    "last_message_at": None, "reason": None,
                })
                sink.update_connection(state)
                session: _Session | None = None
                try:
                    async with self._connector(
                        group.url,
                        open_timeout=self._settings.open_timeout,
                        close_timeout=self._settings.close_timeout,
                        # websockets replies to server ping frames automatically,
                        # including their payload. No redundant client heartbeat.
                        ping_interval=None, ping_timeout=None,
                        max_size=1_048_576, max_queue=32, proxy=None,
                    ) as socket:
                        started = self._monotonic()
                        session = _Session(started, started)
                        self._generations[group.route] += 1
                        state = state.model_copy(update={
                            "status": ConnectionStatus.CONNECTED, "changed_at": self._clock(),
                            "generation": self._generations[group.route],
                        })
                        sink.update_connection(state)
                        while True:
                            remaining_life = self._settings.rotate_after_seconds - (self._monotonic() - started)
                            remaining_data = self._settings.receive_timeout - (self._monotonic() - session.last_usable)
                            if remaining_life <= 0:
                                raise _ReconnectRequested("connection_rotation")
                            if remaining_data <= 0:
                                raise _ReconnectRequested("stale_stream")
                            try:
                                message = await asyncio.wait_for(socket.recv(), timeout=min(remaining_life, remaining_data))
                            except TimeoutError:
                                reason = "connection_rotation" if remaining_life <= remaining_data else "receive_timeout"
                                raise _ReconnectRequested(reason) from None
                            received_at = self._clock()
                            state = state.model_copy(update={"last_message_at": received_at})
                            try:
                                event = parse_message(message, received_at=received_at, expected_streams=group.names)
                            except MarketDataParseError:
                                state = state.model_copy(update={"malformed_messages": state.malformed_messages + 1})
                                sink.update_connection(state)
                                continue
                            sink.update_connection(state)
                            sink.publish(event, connection_id=group.route.value)
                            age = (received_at - event.event_time).total_seconds()
                            if 0 <= age <= self._settings.stale_after_seconds:
                                session.last_usable = self._monotonic()
                                session.usable_messages += 1
                except _ReconnectRequested as request:
                    reason = str(request)
                except TimeoutError:
                    reason = "connection_timeout"
                except (OSError, WebSocketException):
                    reason = "connection_error"

                # A completed handshake alone never resets backoff during flapping.
                if session is not None and session.usable_messages and (
                    self._monotonic() - session.started >= self._settings.receive_timeout
                ):
                    attempt = 0
                delay = self._backoff.delay(attempt, self._random())
                attempt += 1
                state = state.model_copy(update={
                    "status": ConnectionStatus.RECONNECTING, "changed_at": self._clock(),
                    "reason": reason, "reconnect_attempt": attempt,
                })
                sink.update_connection(state)
                await self._sleep(delay)
        finally:
            sink.update_connection(state.model_copy(update={
                "status": ConnectionStatus.STOPPED, "changed_at": self._clock(), "reason": "shutdown",
            }))
