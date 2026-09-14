import json
import socket
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from backtest_fixtures import bar, historical_decision, wave_bars
from live_paper_fixtures import ManualLiveClock, connect, publish_group, running
from src.application.explanations import MODULES, TERMS
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.live_paper_telemetry import LiveDashboardSnapshot, dashboard_snapshot
from src.application.market_data_hub import MarketDataHub
from src.domain.live_paper import LivePaperStatus
from src.domain.market_data import BookTickerEvent, EventType, MarketConnectionState, MarkPriceEvent
from src.infrastructure.binance.settings import MarketDataSettings
from src.main import create_app

PAPER = ('status', 'portfolio', 'positions', 'decisions', 'events', 'curve', 'snapshot')
PATHS = tuple('/paper/'+name for name in PAPER) + ('/explain/modules', '/explain/terms')


def empty_runtime(enabled=True):
    clock = ManualLiveClock()
    hub = MarketDataHub(('BTCUSDT',), clock=clock.now)
    return LivePaperCoordinator(hub, clock=clock, settings=LivePaperSettings(enabled=enabled))


@asynccontextmanager
async def client_for(runtime=None):
    app = create_app(settings=MarketDataSettings(enabled=False))
    if runtime is not None:
        app.state.live_paper_coordinator = runtime
        app.state.market_data_hub = runtime.hub
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize('path', PATHS)
async def test_disabled_empty_read_only_payloads_are_valid(path):
    runtime = empty_runtime(False)
    async with client_for(runtime) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert 'NaN' not in response.text and 'Infinity' not in response.text
    if path == '/paper/snapshot':
        result = LiveDashboardSnapshot.model_validate(response.json())
        assert result.status.status == 'DISABLED' and result.status.started_at is None
        assert not result.status.configuration.runtime.enabled
        assert not result.decisions and not result.positions.active and not result.curve
        assert result.market[0].candle is None and result.market[0].captured_analysis is None
        assert result.portfolio.state.marked_equity == 100000
    assert not runtime.decisions and not runtime.events and not runtime.portfolio.curve


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['STARTING', 'STOPPING', 'STOPPED', 'ERROR'])
async def test_terminal_or_initial_states_are_explicit(status):
    runtime = empty_runtime()
    runtime._status = LivePaperStatus(status)
    if status == 'ERROR':
        runtime._last_problem = 'runtime_error'
    async with client_for(runtime) as client:
        payload = (await client.get('/paper/status')).json()
    assert payload['status'] == status
    assert payload['reasons'] == (['runtime_error'] if status == 'ERROR' else [])


@pytest.mark.asyncio
async def test_warming_running_and_stale_state_without_http_side_effects(monkeypatch):
    async with running() as (runtime, hub, clock), client_for(runtime) as client:
        initial = runtime.started_at
        data = list(wave_bars())
        await publish_group(runtime, hub, clock, [data[0]])
        assert (await client.get('/paper/status')).json()['status'] == 'WARMING_UP'
        for event in data[1:]:
            await publish_group(runtime, hub, clock, [event])
        before = dashboard_snapshot(runtime).model_dump_json()
        def forbidden(*args, **kwargs):
            raise AssertionError('GET must not evaluate analytical engines')
        monkeypatch.setattr(runtime.analysis.features, 'latest', forbidden)
        monkeypatch.setattr(runtime.analysis, 'evaluate', forbidden)
        for _ in range(3):
            for path in PATHS:
                assert (await client.get(path)).status_code == 200
        snapshot = LiveDashboardSnapshot.model_validate((await client.get('/paper/snapshot')).json())
        assert snapshot.status.status == 'RUNNING' and snapshot.status.started_at == initial
        assert dashboard_snapshot(runtime).model_dump_json() == before
        assert snapshot.as_of == snapshot.status.as_of == snapshot.portfolio.as_of == snapshot.positions.as_of
        latest = snapshot.market[0].captured_analysis
        assert latest.boundary == snapshot.portfolio.valuation_as_of == snapshot.status.last_boundary
        assert latest.boundary == latest.features.generated_at == latest.strategy.generated_at == latest.portfolio.upstream.generated_at
        assert latest.connection_id == 'injected_public' and latest.connection_generation == 1
        assert latest.strategy.settings_id == snapshot.status.configuration.identities.strategies
        assert latest.portfolio.upstream.policy_id == snapshot.status.configuration.identities.decisions
        assert latest.portfolio.policy_id == snapshot.status.configuration.identities.portfolio
        assert latest.features.trend.values is not None
        assert latest.features.microstructure.values is None
        assert len(latest.strategy.assessments) == 3
        assert snapshot.positions.completed_count > 0
        count = len(runtime.decisions)
        clock.advance(seconds=10)
        degraded = (await client.get('/paper/snapshot')).json()
        assert degraded['status']['status'] == 'DEGRADED'
        assert 'market_feed_stale' in degraded['status']['reasons']
        assert len(runtime.decisions) == count
        assert degraded['market'][0]['streams']['kline:1m']['event_age_seconds'] == 10


@pytest.mark.asyncio
async def test_current_market_is_distinct_from_captured_generation_and_evidence():
    async with running() as (runtime, hub, clock), client_for(runtime) as client:
        await publish_group(runtime, hub, clock, [bar()])
        captured = runtime.latest_analyses['BTCUSDT'].model_dump_json()
        connect(hub, clock, generation=2)
        clock.advance(seconds=1)
        # Current open candle is a diagnostic observation, never decision evidence.
        current = bar(1, is_closed=False, event_time=clock.now(), received_at=clock.now(), closed='900')
        hub.publish(current, connection_id='injected_public')
        response = LiveDashboardSnapshot.model_validate((await client.get('/paper/snapshot')).json())
        market = response.market[0]
        assert market.candle.close == 900 and not market.candle.is_closed
        assert market.streams['kline:1m'].generation == 2
        assert market.captured_analysis.connection_generation == 1
        assert market.captured_analysis.model_dump_json() == captured


@pytest.mark.asyncio
async def test_public_book_and_mark_context_are_truthful_and_no_depth_arrays():
    runtime = empty_runtime()
    now = runtime.clock.now()
    runtime.hub.update_connection(MarketConnectionState(connection_id='public', event_types=tuple(EventType),
        status='connected', changed_at=now, generation=4))
    runtime.hub.publish(BookTickerEvent(symbol='BTCUSDT', event_time=now, received_at=now, transaction_time=now,
        update_id=1, bid_price='99', ask_price='101', bid_quantity='2', ask_quantity='3'), connection_id='public')
    runtime.hub.publish(MarkPriceEvent(symbol='BTCUSDT', event_time=now, received_at=now,
        mark_price='100', index_price='99', funding_rate='.0001', next_funding_time=now), connection_id='public')
    async with client_for(runtime) as client:
        item = (await client.get('/paper/snapshot')).json()['market'][0]
    assert item['book_ticker']['bid_price'] == '99' and item['mark_price']['funding_rate'] == '0.0001'
    assert not item['streams']['book_ticker']['stale']
    assert item['candle'] is None and item['captured_analysis'] is None
    assert 'depth' not in item and 'events' not in item


@pytest.mark.asyncio
async def test_unknown_portfolio_never_becomes_zero_or_fake_exit():
    runtime = empty_runtime()
    first = bar()
    runtime.portfolio.advance(first.close_time, [first], [historical_decision(first).decision])
    runtime.portfolio.advance(bar(1).close_time, [bar(1)])
    runtime.portfolio.advance(bar(2).close_time, [])
    runtime.clock.advance(bar(2).close_time)
    async with client_for(runtime) as client:
        payload = (await client.get('/paper/snapshot')).json()
    assert payload['portfolio']['state']['marked_equity'] is None
    assert payload['portfolio']['state']['unrealized_net_pnl'] is None
    assert payload['portfolio']['state']['drawdown'] is None
    assert payload['portfolio']['valuation_complete'] is False
    assert payload['positions']['active'][0]['unrealized_net_pnl'] is None
    assert payload['positions']['active'][0]['position']['status'] == 'INCOMPLETE'
    assert payload['positions']['closed'] == []
    assert float(payload['portfolio']['state']['gross_exposure']) == 10000


@pytest.mark.asyncio
async def test_snapshot_dictionary_copies_do_not_mutate_runtime_and_ids_stable():
    runtime = empty_runtime()
    first = dashboard_snapshot(runtime)
    first.status.counters['external_change'] = 1
    first.status.market.symbols.clear()
    assert not runtime.counts and runtime.hub.status().symbols
    with pytest.raises(ValidationError):
        first.status.running = True
    assert dashboard_snapshot(runtime).status.configuration.identities == dashboard_snapshot(empty_runtime()).status.configuration.identities


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/paper/'+name for name in ('positions', 'decisions', 'events', 'curve', 'snapshot')])
@pytest.mark.parametrize('limit', ['0', '-1', '1001', '1.5', '1.0', 'NaN', 'true', '1e2', ''])
async def test_limits_are_strict_and_bounded(path, limit):
    async with client_for(empty_runtime(False)) as client:
        assert (await client.get(path, params={'limit': limit})).status_code == 422


@pytest.mark.asyncio
async def test_histories_retained_and_response_limits_preserve_order():
    settings = LivePaperSettings(event_history_limit=3, curve_history_limit=4, position_history_limit=2)
    async with running(settings=settings) as (runtime, hub, clock), client_for(runtime) as client:
        for event in wave_bars(6):
            await publish_group(runtime, hub, clock, [event])
        result = (await client.get('/paper/snapshot?limit=2')).json()
        assert len(result['decisions']) == len(result['events']) == len(result['curve']) == 2
        assert result['decisions'][0]['boundary'] > result['decisions'][1]['boundary']
        assert result['curve'][0]['state']['timestamp'] < result['curve'][1]['state']['timestamp']
        assert len((await client.get('/paper/events?limit=1000')).json()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/paper/'+name for name in PAPER])
async def test_uninitialized_runtime_is_sanitized_503(path):
    async with client_for() as client:
        response = await client.get(path)
    assert response.status_code == 503
    assert response.json() == {'detail': 'Virtual paper runtime is not initialized'}


@pytest.mark.asyncio
async def test_missing_market_symbol_is_explicit():
    async with client_for(empty_runtime(False)) as client:
        response = await client.get('/market/UNKNOWN/latest')
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
async def test_all_phase8_routes_get_only(method):
    async with client_for(empty_runtime(False)) as client:
        for path in PATHS:
            assert (await client.request(method, path, json={})).status_code == 405


def test_explanations_complete_immutable_deterministic_and_candid():
    terms = {term.key: term for term in TERMS}
    required = {'ema', 'rsi', 'atr', 'vwap', 'spread', 'volatility', 'score', 'confidence', 'agreement',
        'eligible', 'blocked', 'no_action', 'reservation', 'virtual_position', 'exposure', 'gross_exposure',
        'marked_equity', 'realized_equity', 'peak', 'drawdown', 'pnl', 'fees', 'slippage', 'warmup',
        'stale', 'missing', 'connection_generation', 'paper', 'backtest', 'limits'}
    assert required <= terms.keys() and len(terms) == len(TERMS) <= 100
    for key, words in {'confidence': 'not probability of profit', 'eligible': 'does not guarantee',
        'reservation': 'not an exchange order', 'marked_equity': 'not an exchange balance',
        'pnl': 'virtual simulation units', 'fees': 'assumption', 'slippage': 'assumed',
        'backtest': 'do not predict future returns'}.items():
        assert words in terms[key].explanation
    assert all(not module.can_move_money for module in MODULES)
    assert len({item.key for item in MODULES}) == len(MODULES) == 13
    assert {'codec', 'store', 'recovery'} <= {item.key for item in MODULES}
    with pytest.raises(ValidationError):
        TERMS[0].explanation = 'changed'


def test_openapi_typed_get_only_no_executable_or_private_contract():
    schema = create_app().openapi()
    assert set(PATHS) <= schema['paths'].keys() and len(schema['paths']) == 19
    for path in PATHS:
        assert set(schema['paths'][path]) == {'get'}
        assert 'requestBody' not in schema['paths'][path]['get']
    encoded = json.dumps(schema['components']['schemas'])
    for marker in ('TradeIntent', 'ApprovedTradeIntent', 'api_key', 'api_secret', 'account_id', 'order_type', 'leverage'):
        assert marker not in encoded


@pytest.mark.asyncio
async def test_api_and_disabled_lifespan_cannot_open_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No network in telemetry tests')
    app = create_app(settings=MarketDataSettings(enabled=False), clock=ManualLiveClock())
    with monkeypatch.context() as patch:
        patch.setattr(socket.socket, 'connect', forbidden)
        patch.setattr(socket, 'create_connection', forbidden)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
            for path in PATHS:
                assert (await client.get(path)).status_code == 200
    assert app.state.market_data_hub.status().subscriber_count == 0
