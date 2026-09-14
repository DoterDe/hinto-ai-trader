"""Offline full-pipeline restart and SQLite retention soak; temporary files only.

Run from backend: python tests/soak_paper_persistence.py --bars 2000
The separate storage stress uses small valid checkpoints to test many more
transactions without pretending that they are full analytical replay steps.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_fixtures import wave_bars
from persistence_fixtures import admit, durable_runtime, sample_checkpoint
from test_paper_recovery import authoritative
from src.application.feature_settings import FeatureSettings
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_persistence_codec import CheckpointCodec, canonical_json, checksum
from src.application.paper_persistence_settings import PaperPersistenceSettings
from src.infrastructure.sqlite_paper_store import DurablePaperStore


async def pipeline(root: Path, bars: int, restart_every: int, *, progress=False) -> dict:
    runtime_settings = LivePaperSettings(enabled=True, event_history_limit=5, curve_history_limit=7,
        position_history_limit=3, pending_batch_limit=3)
    features = FeatureSettings(history_limit=50)
    data = tuple(wave_bars(bars))  # finite test input; production histories are separately bounded
    reference = None
    prefixes = {}
    maxima = dict(candles=0, decisions=0, events=0, curve=0, closes=0, seen=0, sealed=0,
                  checkpoints=0, audit=0, evidence=0, pending=0, fingerprints=0)
    for run, width in (('continuous', bars), ('restarted', restart_every)):
        path = root / (run + '.db')
        identities = set()
        reservations, entries, closes = set(), set(), set()
        decisions_digest = hashlib.sha256()
        for start in range(0, bars, width):
            end = min(start + width, bars)
            async with durable_runtime(path, settings=runtime_settings, feature_settings=features,
                start_at=data[start-1].close_time if start else None) as (runtime, hub, clock):
                if start:
                    assert runtime.persistence.state.recovered
                for index, event in enumerate(data[start:end], start):
                    previous_opened = runtime.portfolio.opened_count
                    previous_completed = runtime.portfolio.completed_count
                    await admit(runtime, hub, clock, [event])
                    decision = runtime.decisions[-1].portfolio
                    latest = decision.portfolio_decision_id
                    assert latest not in identities, 'a committed decision was duplicated'
                    identities.add(latest)
                    decisions_digest.update(canonical_json(decision).encode('utf-8'))
                    decisions_digest.update(b'\n')
                    book = runtime.portfolio
                    if decision.reservation_id is not None:
                        assert decision.reservation_id not in reservations
                        reservations.add(decision.reservation_id)
                    if book.opened_count > previous_opened:
                        opened = next(iter(book.active.values())).position_id
                        assert opened not in entries
                        entries.add(opened)
                    if book.completed_count > previous_completed:
                        closed = book.closes[-1].close.close_id
                        assert closed not in closes
                        closes.add(closed)
                    sizes = dict(candles=max(len(h.closed) for h in runtime.analysis.features._histories.values()),
                        decisions=len(runtime.decisions), events=len(runtime.events), curve=len(book.curve),
                        closes=len(book.closes), seen=book.seen_count, sealed=len(runtime.batcher._sealed),
                        checkpoints=runtime.persistence.state.retained_checkpoints,
                        audit=runtime.persistence.state.retained_audit_events, pending=runtime.batcher.pending_count,
                        fingerprints=runtime.batcher.retained_fingerprint_count,
                        evidence=max((len(v.fingerprints) for v in book.evidence.values()), default=0))
                    for key, value in sizes.items():
                        maxima[key] = max(maxima[key], value)
                    assert sizes['candles'] <= 50
                    assert max(sizes['decisions'], sizes['events'], sizes['seen']) <= 5
                    assert sizes['curve'] <= 7 and sizes['closes'] <= 3 and sizes['sealed'] <= 3
                    assert sizes['checkpoints'] <= 3 and sizes['audit'] <= 5 and sizes['evidence'] <= 5
                    assert sizes['pending'] <= 3 and sizes['fingerprints'] <= 3
                    if (index + 1) % restart_every == 0 or index + 1 == bars:
                        prefix = (authoritative(runtime), decisions_digest.hexdigest(),
                                  tuple(sorted(reservations)), tuple(sorted(entries)), tuple(sorted(closes)))
                        if run == 'continuous':
                            prefixes[index + 1] = prefix
                        else:
                            assert prefix == prefixes[index + 1], 'restart changed an authoritative prefix or identity'
                result = authoritative(runtime)
                completed = runtime.portfolio.completed_count
            assert not [t for t in threading.enumerate() if t.name.startswith('paper-store')]
            assert not [t for t in asyncio.all_tasks() if t.get_name().startswith('live-paper-')]
            if progress:
                print(f'{run}: {end}/{bars} finalized bars; all retention bounds and cleanup checks passed', flush=True)
        assert len(identities) == bars
        assert completed > 0 and len(closes) == completed
        if reference is None:
            reference = result
        else:
            assert result == reference, 'restart changed authoritative accounting or analytical identities'
    return {'bars_per_run': bars, 'runs': 2, 'restart_segments': (bars + restart_every - 1) // restart_every,
        'authoritative_equal': True, 'authoritative_checksum': checksum(canonical_json(reference)),
        'completed_positions': completed, 'decision_sequence_checksum': decisions_digest.hexdigest(),
        'unique_reservations': len(reservations), 'unique_entries': len(entries), 'unique_closes': len(closes),
        'prefixes_compared': len(prefixes), 'maxima': maxima, 'orphan_workers_tasks_subscribers': 0}


def storage(root: Path, count: int, *, progress=False) -> dict:
    store = DurablePaperStore(PaperPersistenceSettings(enabled=True, path=root / 'storage.db',
        checkpoint_history=3, event_history=5))
    store.open()
    expected = None
    samples = []
    try:
        for index in range(count):
            envelope = CheckpointCodec.encode(sample_checkpoint(index))
            counts = store.commit(envelope, expected=expected)
            expected = envelope.checkpoint_id
            assert counts == (min(index + 1, 3), min(index + 1, 5))
            if index in (min(99, count - 1), count // 2, count - 1):
                # Explicit WAL maintenance belongs to this offline validation,
                # not a browser control. Freelist pages are reusable, not lost.
                store.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                samples.append({'checkpoints_written': index + 1, 'file_bytes': store.path.stat().st_size,
                    'pages': store.connection.execute('PRAGMA page_count').fetchone()[0],
                    'free_pages': store.connection.execute('PRAGMA freelist_count').fetchone()[0]})
            if progress and (index + 1) % 5000 == 0:
                print(f'Storage: {index+1}/{count} atomic checkpoints; retention 3 checkpoints / 5 audit events', flush=True)
        assert store.load().checkpoint_id == expected
        if count >= 200:
            assert samples[-1]['pages'] <= samples[0]['pages'] + 16, 'obsolete checkpoint pages grew without reuse'
        return {'transactions': count, 'retained_checkpoints': counts[0], 'retained_audit_events': counts[1],
            'wal_checkpoint_samples': samples, 'logical_boundedness': True}
    finally:
        store.close()


async def run(root: Path, bars: int, restart_every: int, storage_checkpoints: int, *, progress=False) -> dict:
    result = await pipeline(root, bars, restart_every, progress=progress)
    return {'pipeline': result, 'storage': storage(root, storage_checkpoints, progress=progress)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars', type=int, default=2000)
    parser.add_argument('--restart-every', type=int, default=100)
    parser.add_argument('--storage-checkpoints', type=int, default=20000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.bars < 80 or args.restart_every < 1 or args.storage_checkpoints < 1:
        parser.error('need at least 80 bars and positive retention stress counts')
    # Environment-independent offline fixture assumptions, not strategy fitting.
    for name in tuple(os.environ):
        if name.startswith(('FEATURE_', 'STRATEGY_', 'DECISION_', 'BACKTEST_', 'PORTFOLIO_', 'LIVE_PAPER_', 'PAPER_PERSISTENCE_')):
            del os.environ[name]
    with tempfile.TemporaryDirectory(prefix='hinto-paper-soak-') as directory:
        report = asyncio.run(run(Path(directory), args.bars, args.restart_every, args.storage_checkpoints, progress=True))
    content = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(content, encoding='utf-8', newline='\n')
    print(content)
