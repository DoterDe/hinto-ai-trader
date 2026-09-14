import pytest

from backtest_fixtures import bar
from persistence_fixtures import admit, durable_runtime
from test_live_paper_api import client_for, empty_runtime
from src.domain.paper_persistence import PersistenceStatus


@pytest.mark.asyncio
@pytest.mark.parametrize('state', tuple(PersistenceStatus))
async def test_safe_separate_persistence_dimension(state):
    runtime = empty_runtime()
    runtime.persistence.state = runtime.persistence.state.model_copy(update={'status': state})
    async with client_for(runtime) as client:
        snapshot = (await client.get('/paper/snapshot')).json()
        status = (await client.get('/paper/status')).json()
    assert snapshot['status']['persistence'] == status['persistence']
    assert status['persistence']['status'] == state.value
    assert status['status'] == 'STARTING'  # persistence does not replace runtime health
    assert 'path' not in status['persistence']


@pytest.mark.asyncio
async def test_gets_never_write_read_store_or_advance_accounting(tmp_path, monkeypatch):
    async with durable_runtime(tmp_path / 'private-host-directory.db') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        before = runtime.persistence.state.model_dump_json(), tuple(runtime.decisions), runtime.portfolio.closed_pnl
        def forbidden(*args, **kwargs):
            raise AssertionError('GET must not access persistence or advance engines')
        monkeypatch.setattr(runtime.persistence.store, 'load', forbidden)
        monkeypatch.setattr(runtime.persistence.store, 'commit', forbidden)
        monkeypatch.setattr(runtime.analysis, 'evaluate', forbidden)
        monkeypatch.setattr(runtime.portfolio, 'advance', forbidden)
        async with client_for(runtime) as client:
            for path in ('/paper/status', '/paper/snapshot', '/paper/portfolio', '/paper/positions'):
                response = await client.get(path)
                assert response.status_code == 200
                assert 'private-host-directory' not in response.text and 'NaN' not in response.text and 'Infinity' not in response.text
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                assert (await client.request(method, '/paper/snapshot')).status_code == 405
            assert (await client.post('/paper/reset')).status_code == 404
        assert before == (runtime.persistence.state.model_dump_json(), tuple(runtime.decisions), runtime.portfolio.closed_pnl)


@pytest.mark.asyncio
async def test_pending_commit_is_visible_as_not_yet_durable(tmp_path):
    async with durable_runtime(tmp_path / 'paper.db') as (runtime, hub, clock):
        await admit(runtime, hub, clock, [bar()])
        runtime.persistence.state = runtime.persistence.state.model_copy(update={'has_uncommitted_changes': True})
        async with client_for(runtime) as client:
            state = (await client.get('/paper/status')).json()['persistence']
        assert state['has_uncommitted_changes'] is True
        assert state['checkpoint_id'] == runtime.persistence.state.checkpoint_id
