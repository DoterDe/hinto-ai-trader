"""Explicit real-time boundary; tests replace all three clock operations."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Protocol


class LiveClock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class SystemLiveClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
