"""Bounded canonical JSON; no filesystem, pickle, compression or network access."""

import json
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from src.application.historical_dataset import verify_historical_dataset
from src.domain.historical_dataset import MAX_JSON_BYTES, SCHEMA_VERSION, HistoricalDataset, require_utc


def _value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _value(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite dataset decimal")
        sign, digits, exponent = value.as_tuple()
        text = "".join(str(digit) for digit in digits).rstrip("0")
        return f"{'-' if sign else ''}{text}e{exponent + len(digits) - len(text)}" if text else "0"
    if isinstance(value, datetime):
        require_utc(value)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ValueError("unsupported dataset JSON value")


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate dataset JSON key")
        result[key] = value
    return result


def _noninteger(value: str) -> None:
    raise ValueError("dataset JSON requires exact decimal strings, not float tokens")


class HistoricalDatasetCodec:
    @staticmethod
    def encode(dataset: HistoricalDataset) -> bytes:
        dataset = verify_historical_dataset(dataset)
        payload = (json.dumps(_value(dataset), sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        if len(payload) > MAX_JSON_BYTES:
            raise ValueError("dataset JSON exceeds byte limit")
        return payload

    @staticmethod
    def decode(payload: bytes) -> HistoricalDataset:
        if not isinstance(payload, bytes) or len(payload) > MAX_JSON_BYTES:
            raise ValueError("dataset JSON requires bounded UTF-8 bytes")
        try:
            raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_constant=_noninteger, parse_float=_noninteger)
            if (not isinstance(raw, dict) or not isinstance(raw.get("manifest"), dict)
                    or raw["manifest"].get("schema_version") != SCHEMA_VERSION):
                raise ValueError("explicit supported dataset schema is required")
            dataset = HistoricalDataset.model_validate(raw)
            return verify_historical_dataset(dataset)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise ValueError("invalid historical dataset JSON") from exc
