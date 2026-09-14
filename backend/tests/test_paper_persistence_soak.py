import pytest

from soak_paper_persistence import pipeline, storage


@pytest.mark.asyncio
async def test_repeated_restart_bounded_full_pipeline(tmp_path):
    report = await pipeline(tmp_path, 120, 10)
    assert report['authoritative_equal'] and report['restart_segments'] == 12
    assert report['maxima']['candles'] == 50
    assert report['orphan_workers_tasks_subscribers'] == 0


def test_many_sqlite_transactions_reuse_obsolete_pages(tmp_path):
    report = storage(tmp_path, 300)
    assert report['retained_checkpoints'] == 3 and report['retained_audit_events'] == 5
    assert report['logical_boundedness']
