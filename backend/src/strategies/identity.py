"""Stable content identities; no random IDs or process-local deduplication."""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.domain.features import FeatureSnapshot
from src.domain.strategies import FeatureGroupName


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("identity requires finite values")
        sign, digits, exponent = value.as_tuple()
        text = "".join(str(digit) for digit in digits).rstrip("0")
        if not text:
            return {"decimal": "0"}
        return {"decimal": f"{'-' if sign else ''}{text}e{exponent + len(digits) - len(text)}"}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("identity requires aware timestamps")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def identity(prefix: str, value: Any) -> str:
    content = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return prefix + "_" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def snapshot_identity(snapshot: FeatureSnapshot) -> str:
    return identity("features", snapshot)


def observation_identity(snapshot: FeatureSnapshot, groups: tuple[FeatureGroupName, ...]) -> str:
    """Identify the inputs actually used, independent of API read time.

    Closed-candle features are identified by their close time and values, not
    the timestamp of a subsequent open-candle refresh. Book inputs retain their
    individual event/receipt times. Reconnect and history-reset provenance stay.
    """
    streams = {"book_ticker" if name == "microstructure" else f"kline:{snapshot.interval}"
               for name in groups}
    sources = []
    for source in snapshot.sources:
        if source.stream in streams:
            item = source.model_dump(mode="python")
            if source.stream != "book_ticker":
                item.pop("event_time")
                item.pop("received_at")
            sources.append(item)
    return identity("observation", {
        "symbol": snapshot.symbol, "interval": snapshot.interval,
        "closed_candle_time": snapshot.closed_candle_time,
        "history_resets": snapshot.history_resets,
        "last_history_reset": snapshot.last_history_reset,
        "groups": {name: getattr(snapshot, name) for name in sorted(set(groups))},
        "sources": sorted(sources, key=lambda item: item["stream"]),
    })
