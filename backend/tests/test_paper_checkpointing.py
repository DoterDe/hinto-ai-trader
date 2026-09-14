import asyncio
import threading

import pytest

from backtest_fixtures import bar, wave_bars
from live_paper_fixtures import second_bar
from live_paper_fixtures import connect
from persistence_fixtures import admit, durable_runtime
from src.application.backtest_identity import DatasetIdentity
from src.application.paper_persistence_codec import CheckpointCodec
from src.application.paper_position_evidence import PositionEvidenceIdentity


@pytest.mark.asyncio
async def test_checkpoint_only_after_complete_boundary_and_duplicate_no_extra(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db', symbols=('BTCUSDT', 'ETHUSDT')) as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar(is_closed=False)])
        assert runtime.persistence.state.durable_boundary is None
        await admit(runtime, hub, clock, [bar()])
        assert runtime.batcher.pending_count == 1 and runtime.persistence.state.durable_boundary is None
        await admit(runtime, hub, clock, [bar(symbol='ETHUSDT')])
        state = runtime.persistence.state
        assert state.status == 'DURABLE' and state.retained_checkpoints == 1 and state.durable_boundary == bar().close_time
        envelope = await runtime.persistence._call(runtime.persistence.store.load)
        saved = CheckpointCodec.decode(envelope)
        assert len(saved.decisions) == 2 and saved.ledger.last_boundary == saved.batcher.watermark
        assert not hasattr(saved.batcher, 'pending')
        await admit(runtime, hub, clock, [bar()])
        assert runtime.counts['duplicate_bar'] == 1 and runtime.persistence.state.checkpoint_id == state.checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_filters_later_sealed_but_unapplied_groups(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db', symbols=('BTCUSDT', 'ETHUSDT'), interval='1s') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [second_bar()])
        await admit(runtime, hub, clock, [second_bar(1), second_bar(1, symbol='ETHUSDT')])
        saved = []
        original = runtime.persistence.store.commit
        def inspect(envelope, **kwargs):
            saved.append(CheckpointCodec.decode(envelope))
            return original(envelope, **kwargs)
        runtime.persistence.store.commit = inspect
        await admit(runtime, hub, clock, [second_bar(symbol='ETHUSDT')])
        assert len(saved) == 2
        assert saved[0].batcher.watermark == second_bar().close_time
        assert all(s.boundary <= saved[0].durable_boundary for s in saved[0].batcher.sealed)
        assert saved[1].durable_boundary == second_bar(1).close_time


@pytest.mark.asyncio
async def test_rotation_between_returned_groups_cannot_relabel_old_bars_as_new_generation(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db', symbols=('BTCUSDT', 'ETHUSDT'), interval='1s') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [second_bar()])
        await admit(runtime, hub, clock, [second_bar(1), second_bar(1, symbol='ETHUSDT')])
        original = runtime.persistence.checkpoint
        async def rotate_after_commit(owner):
            await original(owner)
            connect(hub, clock, generation=2)
        runtime.persistence.checkpoint = rotate_after_commit
        await admit(runtime, hub, clock, [second_bar(symbol='ETHUSDT')])
        assert runtime.portfolio.last_boundary == second_bar(1).close_time
        assert len(runtime.decisions) == 2  # only the first group was still current
        assert runtime.counts['generation_changed_during_batch'] == 1
        assert all(a.boundary == second_bar().close_time for a in runtime.decisions)


@pytest.mark.asyncio
async def test_failure_never_publishes_uncommitted_boundary(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        previous = runtime.persistence.state
        runtime.persistence.store.fault = lambda stage: (_ for _ in ()).throw(OSError('simulated')) if stage == 'before_commit' else None
        with pytest.raises(OSError):
            await admit(runtime, hub, clock, [bar(1)])
        state = runtime.persistence.snapshot(runtime.portfolio.last_boundary)
        assert state.status == 'DEGRADED' and state.has_uncommitted_changes
        assert state.durable_boundary == previous.durable_boundary and state.in_memory_boundary == bar(1).close_time
        assert runtime.persistence.halted
        saved = await runtime.persistence._call(runtime.persistence.store.load)
        assert saved.checkpoint_id == previous.checkpoint_id


@pytest.mark.asyncio
async def test_actual_analytical_pipeline_bounded_checkpoints_and_evidence(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        for candle in wave_bars():
            await admit(runtime, hub, clock, [candle])
        state = runtime.persistence.state
        assert (state.retained_checkpoints, state.retained_audit_events) == (3, 5)
        assert runtime.portfolio.completed_count > 0
        saved = CheckpointCodec.decode(await runtime.persistence._call(runtime.persistence.store.load))
        assert len(saved.decisions) <= 15 and len(saved.ledger.curve) <= 20 and len(saved.ledger.closes) <= 10
        assert saved.ledger.closed_pnl == runtime.portfolio.closed_pnl
        for evidence in runtime.portfolio.evidence.values():
            assert len(evidence.fingerprints) == evidence.count <= runtime.costs.holding_period_bars


def test_close_evidence_identity_unchanged_and_exactly_restorable():
    original, durable = DatasetIdentity(), PositionEvidenceIdentity(5)
    for index in range(5):
        original.add(bar(index))
        durable.add(bar(index))
    restored = PositionEvidenceIdentity(5, tuple(durable.fingerprints))
    assert original.value == durable.value == restored.value
    assert original.count == durable.count == restored.count == 5
    with pytest.raises(ValueError, match='horizon'):
        durable.add(bar(5))
    with pytest.raises(ValueError, match='fingerprint'):
        PositionEvidenceIdentity(5, ('bad',))


@pytest.mark.asyncio
async def test_cancel_waits_for_worker_commit_before_close(tmp_path):
    entered, release = threading.Event(), threading.Event()
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        def block(stage):
            if stage == 'before_commit':
                entered.set()
                assert release.wait(10)
        runtime.persistence.store.fault = block
        task = asyncio.create_task(admit(runtime, hub, clock, [bar()]))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await runtime.persistence._call(runtime.persistence.store.load)) is not None
    assert not [t for t in threading.enumerate() if t.name.startswith('paper-store')]
