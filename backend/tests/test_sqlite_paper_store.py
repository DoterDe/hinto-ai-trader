import sqlite3
import time
import subprocess
import sys
from pathlib import Path

import pytest

from persistence_fixtures import sample_checkpoint
from src.application.paper_persistence_codec import CheckpointCodec, CheckpointCorrupt, CheckpointIncompatible
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.infrastructure.sqlite_paper_store import DurablePaperStore, StoreBusy


def store_at(tmp_path, **settings):
    return DurablePaperStore(PaperPersistenceSettings(path=tmp_path / 'paper.sqlite3', **settings))


def test_new_schema_explicit_durability_and_reopen(tmp_path):
    store = store_at(tmp_path, busy_timeout_ms=25)
    store.open()
    assert store.load() is None and store.counts() == (0, 0)
    for pragma, expected in [('foreign_keys', 1), ('journal_mode', 'wal'), ('synchronous', 2), ('busy_timeout', 25)]:
        assert store.connection.execute('PRAGMA ' + pragma).fetchone()[0] == expected
    envelope = CheckpointCodec.encode(sample_checkpoint())
    assert store.commit(envelope, expected=None) == (1, 1)
    store.close()
    store.open()
    assert store.load() == envelope
    store.close()


@pytest.mark.parametrize('stage', ['before_write', 'after_write', 'before_commit', 'after_commit'])
def test_atomic_faults_restore_previous_or_complete_new(tmp_path, stage):
    store = store_at(tmp_path)
    store.open()
    first, second = (CheckpointCodec.encode(sample_checkpoint(i)) for i in range(2))
    store.commit(first, expected=None)
    def fail(point):
        if point == stage:
            raise OSError('injected disk failure')
    store.fault = fail
    with pytest.raises(OSError):
        store.commit(second, expected=first.checkpoint_id)
    store.close()
    store.open()
    assert store.load() == (second if stage == 'after_commit' else first)
    assert store.counts() == ((2, 2) if stage == 'after_commit' else (1, 1))
    store.close()


def test_first_transaction_failure_does_not_leave_half_session(tmp_path):
    store = store_at(tmp_path)
    store.open()
    store.fault = lambda stage: (_ for _ in ()).throw(OSError('disk')) if stage == 'after_write' else None
    with pytest.raises(OSError):
        store.commit(CheckpointCodec.encode(sample_checkpoint()), expected=None)
    assert store.load() is None and store.counts() == (0, 0)
    store.close()


def test_independent_bounded_checkpoint_and_audit_retention(tmp_path):
    store = store_at(tmp_path, checkpoint_history=2, event_history=3)
    store.open()
    expected = None
    for index in range(20):
        envelope = CheckpointCodec.encode(sample_checkpoint(index))
        counts = store.commit(envelope, expected=expected)
        expected = envelope.checkpoint_id
        assert counts == (min(index + 1, 2), min(index + 1, 3))
    assert store.load() == envelope
    store.close()


def test_one_owner_and_stale_writer_rejected(tmp_path):
    store = store_at(tmp_path)
    store.open()
    other = store_at(tmp_path)
    with pytest.raises(StoreBusy):
        other.open()
    first = CheckpointCodec.encode(sample_checkpoint())
    store.commit(first, expected=None)
    with pytest.raises(StoreBusy):
        store.commit(CheckpointCodec.encode(sample_checkpoint(1)), expected=None)
    assert store.load() == first
    store.close()
    other.open()
    other.close()


@pytest.mark.parametrize('mutation', ['payload', 'checksum', 'metadata', 'head', 'schema', 'missing_table', 'not_sqlite'])
def test_corrupt_or_incompatible_latest_never_falls_back(tmp_path, mutation):
    store = store_at(tmp_path)
    store.open()
    first = CheckpointCodec.encode(sample_checkpoint())
    second = CheckpointCodec.encode(sample_checkpoint(1))
    store.commit(first, expected=None)
    store.commit(second, expected=first.checkpoint_id)
    store.close()
    if mutation == 'not_sqlite':
        store.path.write_bytes(b'not a database')
    else:
        with sqlite3.connect(store.path) as conn:
            if mutation in ('payload', 'checksum'):
                conn.execute(f'UPDATE paper_checkpoints SET {mutation}=? WHERE checkpoint_id=?', ('broken', second.checkpoint_id))
            elif mutation == 'metadata':
                conn.execute("UPDATE paper_sessions SET created_at='wrong'")
            elif mutation == 'head':
                conn.execute('DELETE FROM paper_checkpoints WHERE checkpoint_id=?', (second.checkpoint_id,))
            elif mutation == 'schema':
                conn.execute('UPDATE schema_metadata SET version=99')
            else:
                conn.execute('DROP TABLE paper_audit_events')
    try:
        with pytest.raises((CheckpointCorrupt, CheckpointIncompatible, sqlite3.DatabaseError)):
            store.open()
            store.load()
    finally:
        store.close()


def test_busy_timeout_is_bounded_and_rolls_back(tmp_path):
    store = store_at(tmp_path, busy_timeout_ms=20)
    store.open()
    with sqlite3.connect(store.path, isolation_level=None) as blocker:
        blocker.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            store.commit(CheckpointCodec.encode(sample_checkpoint()), expected=None)
        elapsed = time.monotonic() - started
        assert 0.01 <= elapsed < 2
        blocker.execute('ROLLBACK')
    assert store.load() is None
    store.close()


def test_same_boundary_and_configuration_rewrite_rejected(tmp_path):
    store = store_at(tmp_path)
    store.open()
    first = CheckpointCodec.encode(sample_checkpoint())
    store.commit(first, expected=None)
    with pytest.raises(ValueError, match='increase'):
        store.commit(first, expected=first.checkpoint_id)
    checkpoint = sample_checkpoint(1)
    changed = checkpoint.model_copy(update={'compatibility': checkpoint.compatibility.model_copy(update={'interval': '5m'}), 'analysis': None})
    with pytest.raises(CheckpointIncompatible):
        store.commit(CheckpointCodec.encode(changed), expected=first.checkpoint_id)
    assert store.counts() == (1, 1)
    store.close()


@pytest.mark.parametrize('statement', ['INSERT INTO paper_checkpoints', 'UPDATE paper_sessions', 'COMMIT'])
def test_actual_sql_statement_failure_rolls_back_complete_transaction(tmp_path, statement):
    store = store_at(tmp_path)
    store.open()
    first = CheckpointCodec.encode(sample_checkpoint())
    store.commit(first, expected=None)
    connection = store.connection
    class FailingConnection:
        def execute(self, sql, *args):
            if sql.startswith(statement):
                raise sqlite3.OperationalError('injected SQLite write failure')
            return connection.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(connection, name)
    store.connection = FailingConnection()
    with pytest.raises(sqlite3.OperationalError):
        store.commit(CheckpointCodec.encode(sample_checkpoint(1)), expected=first.checkpoint_id)
    store.connection = connection
    assert not connection.in_transaction and store.load() == first and store.counts() == (1, 1)
    store.close()


@pytest.mark.parametrize('stage', ['before_commit', 'after_commit'])
def test_abrupt_subprocess_exit_before_and_after_commit(tmp_path, stage):
    store = store_at(tmp_path)
    store.open()
    first = CheckpointCodec.encode(sample_checkpoint())
    store.commit(first, expected=None)
    store.close()
    script = '''
import os, sys
sys.path.insert(0, 'tests')
from persistence_fixtures import sample_checkpoint
from src.application.paper_persistence_codec import CheckpointCodec
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.infrastructure.sqlite_paper_store import DurablePaperStore
store = DurablePaperStore(PaperPersistenceSettings(enabled=True, path=sys.argv[1]))
store.open()
previous = store.load()
store.fault = lambda point: os._exit(17) if point == sys.argv[2] else None
store.commit(CheckpointCodec.encode(sample_checkpoint(1)), expected=previous.checkpoint_id)
raise AssertionError('crash point not reached')
'''
    result = subprocess.run([sys.executable, '-c', script, str(store.path), stage],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 17, result.stderr
    store.open()
    recovered = CheckpointCodec.decode(store.load())
    assert recovered == sample_checkpoint(1 if stage == 'after_commit' else 0)
    store.close()
