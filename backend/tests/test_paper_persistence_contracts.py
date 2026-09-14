import json
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from persistence_fixtures import sample_checkpoint
from src.application.paper_persistence_codec import (
    CheckpointCodec, CheckpointCorrupt, CheckpointIncompatible, canonical_json, checksum,
)
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.domain.paper_persistence import PaperCheckpoint, PersistenceStatus


def test_defaults_and_no_file_side_effect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PAPER_PERSISTENCE_ENABLED')
    settings = PaperPersistenceSettings()
    assert settings.enabled and settings.path == Path('data/paper_runtime.sqlite3')
    assert (settings.checkpoint_history, settings.event_history, settings.busy_timeout_ms, settings.resume_policy) == (32, 5000, 5000, 'strict')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('field,value', [
    ('enabled', 1), ('enabled', 'yes'), ('checkpoint_history', 0), ('checkpoint_history', 257),
    ('checkpoint_history', True), ('event_history', 0), ('event_history', 100001),
    ('event_history', 2.5), ('busy_timeout_ms', 0), ('busy_timeout_ms', 60001),
    ('busy_timeout_ms', '-1'), ('resume_policy', 'fresh'), ('resume_policy', 'lenient'),
])
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        PaperPersistenceSettings(**{field: value})


@pytest.mark.parametrize('path', ['', ':memory:', 'file:data.db', 'https://host/db.sqlite',
    '//host/share/db.sqlite', '\\\\host\\share\\db.sqlite', '../escape.db', 'data/../escape.db',
    '~/data.db', 'data.txt', 'data.db\n', 'postgresql://host/db', '\\\\?\\C:\\data.db'])
def test_nonlocal_or_ambiguous_paths_rejected(path):
    with pytest.raises(ValidationError):
        PaperPersistenceSettings(path=path)


def test_local_path_and_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPER_PERSISTENCE_PATH', str(tmp_path / 'paper.sqlite3'))
    monkeypatch.setenv('PAPER_PERSISTENCE_ENABLED', 'false')
    monkeypatch.setenv('PAPER_PERSISTENCE_CHECKPOINT_HISTORY', '4')
    settings = PaperPersistenceSettings()
    assert settings.path == tmp_path / 'paper.sqlite3' and not settings.enabled and settings.checkpoint_history == 4
    directory = tmp_path / 'directory.db'
    directory.mkdir()
    with pytest.raises(ValidationError):
        PaperPersistenceSettings(path=directory)


def test_exact_canonical_round_trip_and_identity():
    checkpoint = sample_checkpoint()
    envelope = CheckpointCodec.encode(checkpoint)
    decoded = CheckpointCodec.decode(envelope)
    assert decoded == checkpoint and CheckpointCodec.encode(decoded) == envelope
    assert decoded.ledger.peak.as_tuple() == Decimal('100000.0000').as_tuple()
    assert decoded.durable_boundary.tzinfo is not None
    assert decoded.durable_boundary == checkpoint.durable_boundary
    assert json.loads(envelope.payload)['last_problem'] is None
    assert envelope.checksum == checksum(envelope.payload)


def test_key_order_is_canonical_but_insertion_ordered_dedupe_is_preserved():
    checkpoint = sample_checkpoint()
    data = checkpoint.model_dump()
    reordered = PaperCheckpoint.model_validate(dict(reversed(tuple(data.items()))))
    assert CheckpointCodec.encode(checkpoint) == CheckpointCodec.encode(reordered)
    book = checkpoint.ledger.model_copy(update={'seen': (('second', 'b'), ('first', 'a'))})
    decoded = CheckpointCodec.decode(CheckpointCodec.encode(checkpoint.model_copy(update={'ledger': book})))
    assert decoded.ledger.seen == (('second', 'b'), ('first', 'a'))


@pytest.mark.parametrize('value', ['0E-20', '-0.0000', '123456789012345678901234567890.123456789', '1E+100', '1E-100'])
def test_decimal_fidelity(value):
    checkpoint = sample_checkpoint()
    pnl = checkpoint.ledger.closed_pnl.model_copy(update={'gross_pnl': Decimal(value), 'net_pnl': Decimal(value)})
    changed = checkpoint.model_copy(update={'ledger': checkpoint.ledger.model_copy(update={'closed_pnl': pnl})})
    result = CheckpointCodec.decode(CheckpointCodec.encode(changed))
    assert result.ledger.closed_pnl.net_pnl.as_tuple() == Decimal(value).as_tuple()


@pytest.mark.parametrize('value', [Decimal('NaN'), Decimal('Infinity'), Decimal('-Infinity'), float('nan'), float('inf'), object()])
def test_nonfinite_and_arbitrary_values_rejected(value):
    with pytest.raises(ValueError):
        canonical_json(value)


@pytest.mark.parametrize('offset', [None, timezone(timedelta(hours=5))])
def test_timestamps_require_utc(offset):
    checkpoint = sample_checkpoint()
    changed = checkpoint.model_copy(update={'checkpoint_at': checkpoint.checkpoint_at.replace(tzinfo=offset)})
    with pytest.raises(ValueError):
        CheckpointCodec.encode(changed)


@pytest.mark.parametrize('mutation', ['checksum', 'id', 'truncated', 'extra', 'duplicate', 'nan', 'invalid_decimal', 'null_equity'])
def test_corruption_rejected_even_if_checksum_recomputed(mutation):
    envelope = CheckpointCodec.encode(sample_checkpoint())
    data = json.loads(envelope.payload)
    if mutation == 'checksum':
        envelope = envelope.model_copy(update={'checksum': '0' * 64})
    elif mutation == 'id':
        envelope = envelope.model_copy(update={'checkpoint_id': 'wrong'})
    else:
        if mutation == 'extra':
            data['secret'] = 'forbidden-field'
        if mutation == 'invalid_decimal':
            data['ledger']['peak'] = 'invalid'
        if mutation == 'null_equity':
            data['ledger']['peak'] = None
        payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
        if mutation == 'truncated':
            payload = payload[:-1]
        if mutation == 'duplicate':
            payload = '{"version":1,' + payload[1:]
        if mutation == 'nan':
            payload = payload.replace('"peak":"100000.0000"', '"peak":NaN')
        envelope = envelope.model_copy(update={'payload': payload, 'checksum': checksum(payload)})
    with pytest.raises(CheckpointCorrupt):
        CheckpointCodec.decode(envelope)


@pytest.mark.parametrize('kind', ['schema', 'payload'])
def test_unknown_version_fails_closed(kind):
    envelope = CheckpointCodec.encode(sample_checkpoint())
    if kind == 'schema':
        envelope = envelope.model_copy(update={'schema_version': 2})
    else:
        payload = envelope.payload.replace('"version":1', '"version":2')
        envelope = envelope.model_copy(update={'payload': payload, 'checksum': checksum(payload)})
    with pytest.raises(CheckpointIncompatible):
        CheckpointCodec.decode(envelope)


@pytest.mark.parametrize('mutation', ['watermark', 'boundary', 'history_bound', 'scope', 'future_bar', 'open_bar', 'dedupe', 'evidence', 'pending_group'])
def test_impossible_or_unbounded_state_rejected(mutation):
    data = sample_checkpoint().model_dump()
    if mutation == 'watermark':
        data['batcher']['watermark'] -= timedelta(minutes=1)
    elif mutation == 'boundary':
        data['ledger']['last_boundary'] -= timedelta(minutes=1)
    elif mutation == 'history_bound':
        data['analysis']['histories'][0]['bars'] *= 51
    elif mutation == 'scope':
        data['analysis']['histories'][0]['symbol'] = 'ETHUSDT'
    elif mutation == 'future_bar':
        data['analysis']['clock'] += timedelta(minutes=1)
    elif mutation == 'open_bar':
        data['analysis']['histories'][0]['bars'][0]['is_closed'] = False
    elif mutation == 'dedupe':
        data['ledger']['seen'] = (('same', 'a'), ('same', 'b'))
    elif mutation == 'evidence':
        data['ledger']['marks'] = (('BTCUSDT', Decimal(0)),)
    else:
        data['batcher']['pending'] = []
    with pytest.raises(ValidationError):
        PaperCheckpoint.model_validate(data)


def test_explicit_separate_health_states():
    assert {s.value for s in PersistenceStatus} == {'DISABLED', 'NEW_SESSION', 'RECOVERING', 'RECOVERED',
        'DURABLE', 'DEGRADED', 'INCOMPATIBLE', 'CORRUPT', 'ERROR'}
