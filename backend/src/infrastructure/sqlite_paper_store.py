"""Single-owner local paper checkpoints, explicit atomic SQLite transactions.

The connection is created and used on one thread. The async owner supplies that
thread; this module also supports synchronous offline validation tools.
"""

import sqlite3
import json
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from src.application.paper_persistence_codec import (
    CheckpointCodec, CheckpointCorrupt, CheckpointIncompatible, canonical_json, checksum,
)
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.domain.paper_persistence import CheckpointEnvelope, ContinuityFence, SCHEMA_VERSION

_OWNERS: set[Path] = set()
_OWNER_LOCK = Lock()

_SCHEMA = (
    'CREATE TABLE schema_metadata(version INTEGER NOT NULL)',
    '''CREATE TABLE paper_sessions (
        slot INTEGER PRIMARY KEY CHECK(slot=1), session_id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, compatibility TEXT NOT NULL,
        latest_checkpoint_id TEXT, continuity_fence TEXT)''',
    '''CREATE TABLE paper_checkpoints (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        checkpoint_id TEXT NOT NULL UNIQUE,
        session_id TEXT NOT NULL REFERENCES paper_sessions(session_id),
        schema_version INTEGER NOT NULL, checksum TEXT NOT NULL, payload TEXT NOT NULL)''',
    '''CREATE TABLE paper_audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES paper_sessions(session_id),
        event_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, metadata TEXT NOT NULL)''',
)


class StoreBusy(RuntimeError):
    pass


class DurablePaperStore:
    def __init__(self, settings: PaperPersistenceSettings, *, fault: Callable[[str], None] | None = None) -> None:
        self.settings = PaperPersistenceSettings.model_validate(settings)
        self.path = self.settings.path.resolve()
        self.fault = fault or (lambda stage: None)
        self.connection: sqlite3.Connection | None = None
        self._owned = False

    def open(self) -> None:
        if self.connection is not None:
            raise RuntimeError('paper store already open')
        with _OWNER_LOCK:
            if self.path in _OWNERS:
                raise StoreBusy('paper store already has an owner')
            _OWNERS.add(self.path)
            self._owned = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=self.settings.busy_timeout_ms / 1000)
            self.connection = conn
            conn.execute('PRAGMA foreign_keys=ON')
            # PRAGMA does not support bound parameters; this value is a validated integer.
            conn.execute(f'PRAGMA busy_timeout={self.settings.busy_timeout_ms:d}')
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing:
                if 'schema_metadata' not in existing:
                    raise CheckpointIncompatible('unrecognized paper database schema')
                versions = conn.execute('SELECT version FROM schema_metadata').fetchall()
                if versions != [(SCHEMA_VERSION,)]:
                    raise CheckpointIncompatible('unsupported paper database schema')
                required = {'schema_metadata', 'paper_sessions', 'paper_checkpoints', 'paper_audit_events'}
                if not required <= existing:
                    raise CheckpointCorrupt('incomplete paper database schema')
                if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchall():
                    raise CheckpointCorrupt('paper database integrity failure')
            if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
                raise RuntimeError('local paper database requires WAL')
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('PRAGMA wal_autocheckpoint=1000')
            if not existing:
                conn.execute('BEGIN IMMEDIATE')
                try:
                    for statement in _SCHEMA:
                        conn.execute(statement)
                    conn.execute('INSERT INTO schema_metadata VALUES(?)', (SCHEMA_VERSION,))
                    conn.execute('COMMIT')
                except BaseException:
                    conn.execute('ROLLBACK')
                    raise
        except BaseException:
            self.close()
            raise

    def load(self) -> CheckpointEnvelope | None:
        conn = self._connection()
        session = conn.execute('SELECT session_id, created_at, compatibility, latest_checkpoint_id FROM paper_sessions').fetchall()
        rows = conn.execute('SELECT checkpoint_id, schema_version, checksum, payload FROM paper_checkpoints ORDER BY sequence DESC LIMIT 1').fetchall()
        if not session and not rows:
            return None
        if len(session) != 1 or not rows or session[0][3] != rows[0][0]:
            raise CheckpointCorrupt('paper session does not identify its latest committed checkpoint')
        key, version, digest, payload = rows[0]
        if version != SCHEMA_VERSION:
            raise CheckpointIncompatible('unsupported checkpoint schema')
        try:
            envelope = CheckpointEnvelope(checkpoint_id=key, schema_version=version, checksum=digest, payload=payload)
            checkpoint = CheckpointCodec.decode(envelope)
            if (checkpoint.session_id, canonical_json(checkpoint.session_created_at), canonical_json(checkpoint.compatibility)) != session[0][:3]:
                raise CheckpointCorrupt('session metadata does not match checkpoint')
        except ValueError as exc:
            if isinstance(exc, CheckpointIncompatible):
                raise
            raise CheckpointCorrupt('invalid latest checkpoint') from exc
        return envelope

    def commit(self, envelope: CheckpointEnvelope, *, expected: str | None) -> tuple[int, int]:
        checkpoint = CheckpointCodec.decode(envelope)
        conn = self._connection()
        conn.execute('BEGIN IMMEDIATE')
        try:
            current = self.load()
            if (current.checkpoint_id if current else None) != expected:
                raise StoreBusy('paper checkpoint changed outside its authoritative writer')
            if current is not None:
                previous = CheckpointCodec.decode(current)
                if previous.session_id != checkpoint.session_id or previous.compatibility != checkpoint.compatibility:
                    raise CheckpointIncompatible('cannot mix paper sessions or configurations')
                if checkpoint.durable_boundary <= previous.durable_boundary:
                    raise ValueError('durable boundaries must strictly increase')
            else:
                conn.execute('INSERT INTO paper_sessions VALUES(1, ?, ?, ?, NULL, NULL)',
                    (checkpoint.session_id, canonical_json(checkpoint.session_created_at), canonical_json(checkpoint.compatibility)))
            self.fault('before_write')
            conn.execute('INSERT INTO paper_checkpoints(checkpoint_id, session_id, schema_version, checksum, payload) VALUES(?, ?, ?, ?, ?)',
                (envelope.checkpoint_id, checkpoint.session_id, envelope.schema_version, envelope.checksum, envelope.payload))
            self.fault('after_write')
            conn.execute('UPDATE paper_sessions SET latest_checkpoint_id=?, continuity_fence=NULL WHERE slot=1', (envelope.checkpoint_id,))
            conn.execute('INSERT INTO paper_audit_events(session_id,event_id,kind,metadata) VALUES(?,?,?,?)',
                (checkpoint.session_id, envelope.checkpoint_id, 'checkpoint', canonical_json({
                    'boundary': checkpoint.durable_boundary, 'checksum': envelope.checksum})))
            self._retain()
            self.fault('before_commit')
            conn.execute('COMMIT')
        except BaseException:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        self.fault('after_commit')  # crash simulation: durable state is already complete
        return self.counts()

    def _retain(self) -> None:
        conn = self._connection()
        conn.execute('DELETE FROM paper_checkpoints WHERE sequence NOT IN (SELECT sequence FROM paper_checkpoints ORDER BY sequence DESC LIMIT ?)',
            (self.settings.checkpoint_history,))
        conn.execute('DELETE FROM paper_audit_events WHERE sequence NOT IN (SELECT sequence FROM paper_audit_events ORDER BY sequence DESC LIMIT ?)',
            (self.settings.event_history,))

    def save_fence(self, fence: ContinuityFence) -> tuple[int, int]:
        """Persist detected loss, without rewriting/advancing a candle checkpoint."""
        fence = ContinuityFence.model_validate(fence)
        payload = canonical_json(fence)
        encoded = canonical_json({'payload': payload, 'checksum': checksum(payload)})
        conn = self._connection()
        conn.execute('BEGIN IMMEDIATE')
        try:
            latest = self.load()
            if latest is None or latest.checkpoint_id != fence.checkpoint_id:
                raise StoreBusy('continuity fence does not match current checkpoint')
            checkpoint = CheckpointCodec.decode(latest)
            previous = self.load_fence()
            if (fence.watermark < checkpoint.durable_boundary or fence.generation < checkpoint.generation
                    or (previous is not None and (fence.generation < previous.generation or fence.watermark < previous.watermark))):
                raise ValueError('continuity fence cannot move backwards')
            conn.execute('UPDATE paper_sessions SET continuity_fence=? WHERE slot=1', (encoded,))
            conn.execute('INSERT OR IGNORE INTO paper_audit_events(session_id,event_id,kind,metadata) VALUES(?,?,?,?)',
                (checkpoint.session_id, 'fence_' + checksum(payload), 'continuity_loss', encoded))
            self._retain()
            self.fault('before_fence_commit')
            conn.execute('COMMIT')
        except BaseException:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise
        return self.counts()

    def load_fence(self) -> ContinuityFence | None:
        row = self._connection().execute('SELECT continuity_fence FROM paper_sessions WHERE slot=1').fetchone()
        if row is None or row[0] is None:
            return None
        try:
            encoded = json.loads(row[0])
            if set(encoded) != {'payload', 'checksum'} or encoded['checksum'] != checksum(encoded['payload']):
                raise ValueError('invalid fence checksum')
            fence = ContinuityFence.model_validate_json(encoded['payload'])
            if canonical_json(fence) != encoded['payload'] or canonical_json(encoded) != row[0]:
                raise ValueError('noncanonical fence')
            return fence
        except (ValueError, TypeError, KeyError) as exc:
            raise CheckpointCorrupt('invalid continuity fence') from exc

    def counts(self) -> tuple[int, int]:
        conn = self._connection()
        return (conn.execute('SELECT COUNT(*) FROM paper_checkpoints').fetchone()[0],
                conn.execute('SELECT COUNT(*) FROM paper_audit_events').fetchone()[0])

    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError('paper store is closed')
        return self.connection

    def close(self) -> None:
        try:
            if self.connection is not None:
                self.connection.close()
        finally:
            self.connection = None
            if self._owned:
                with _OWNER_LOCK:
                    _OWNERS.discard(self.path)
                self._owned = False
