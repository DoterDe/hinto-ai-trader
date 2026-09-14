"""Canonical, checksummed JSON with exact Decimal/UTC values and closed schemas."""

import hashlib
import hmac
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from src.domain.paper_persistence import CheckpointEnvelope, PaperCheckpoint, SCHEMA_VERSION


class CheckpointCorrupt(ValueError):
    """Untrusted persisted content; never silently replace it with a fresh session."""


class CheckpointIncompatible(ValueError):
    """Unsupported version or mismatched analytical configuration."""


def _value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _value(value.model_dump(mode='python'))
    if isinstance(value, Enum):
        return _value(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('nonfinite checkpoint decimal')
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError('checkpoint timestamps must be aware UTC')
        return value.isoformat(timespec='microseconds')
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError('checkpoint keys must be strings')
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError('unsupported or nonfinite checkpoint value')


def canonical_json(value: object) -> str:
    return json.dumps(_value(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def checksum(payload: str) -> str:
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise CheckpointCorrupt('duplicate checkpoint key')
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise CheckpointCorrupt('nonfinite checkpoint JSON')


class CheckpointCodec:
    @staticmethod
    def encode(checkpoint: PaperCheckpoint) -> CheckpointEnvelope:
        # Validate even frozen model_copy/model_construct inputs.
        checkpoint = PaperCheckpoint.model_validate(checkpoint)
        payload = canonical_json(checkpoint)
        digest = checksum(payload)
        key = checksum(canonical_json((checkpoint.session_id, checkpoint.durable_boundary, digest)))
        return CheckpointEnvelope(checkpoint_id='checkpoint_' + key, checksum=digest, payload=payload)

    @staticmethod
    def decode(envelope: CheckpointEnvelope) -> PaperCheckpoint:
        try:
            if envelope.schema_version != SCHEMA_VERSION:
                raise CheckpointIncompatible('unsupported checkpoint schema')
            envelope = CheckpointEnvelope.model_validate(envelope)
            if not hmac.compare_digest(checksum(envelope.payload), envelope.checksum):
                raise CheckpointCorrupt('checkpoint checksum mismatch')
            raw = json.loads(envelope.payload, object_pairs_hook=_pairs, parse_constant=_constant)
            if not isinstance(raw, dict):
                raise CheckpointCorrupt('checkpoint must be an object')
            if raw.get('version') != 1:
                raise CheckpointIncompatible('unsupported checkpoint payload version')
            checkpoint = PaperCheckpoint.model_validate(raw)
            encoded = CheckpointCodec.encode(checkpoint)
            if encoded != envelope:
                raise CheckpointCorrupt('noncanonical or inconsistent checkpoint')
            return checkpoint
        except CheckpointIncompatible:
            raise
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise CheckpointCorrupt('invalid checkpoint content') from exc
