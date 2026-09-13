from datetime import timedelta
from itertools import permutations

import pytest
from pydantic import ValidationError

from backtest_fixtures import START, bar
from src.application.live_bar_batcher import LiveBarBatcher, canonical_bar
from src.application.live_paper_settings import LivePaperSettings
from src.domain.live_paper import LiveBarBatch, LivePaperEvent, LivePaperStatus


class ManualTimer:
    value = 0.0

    def __call__(self):
        return self.value


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')


def make_batcher(symbols=SYMBOLS, **settings):
    timer = ManualTimer()
    return LiveBarBatcher(symbols, settings=LivePaperSettings(**settings), monotonic=timer), timer


@pytest.mark.parametrize('field', ['batch_timeout_ms', 'event_history_limit', 'curve_history_limit',
    'position_history_limit', 'pending_batch_limit', 'queue_limit'])
@pytest.mark.parametrize('value', [0, -1, True, 1.5, '1.5', 'NaN', 'Infinity', 999999])
def test_strict_bounded_settings(field, value):
    with pytest.raises(ValidationError):
        LivePaperSettings(**{field: value})


def test_defaults_environment_and_immutable_contract(monkeypatch):
    monkeypatch.delenv('LIVE_PAPER_ENABLED', raising=False)
    config = LivePaperSettings()
    assert (config.enabled, config.batch_timeout_ms, config.event_history_limit,
            config.curve_history_limit, config.position_history_limit) == (True, 1500, 1000, 2000, 1000)
    monkeypatch.setenv('LIVE_PAPER_ENABLED', 'false')
    monkeypatch.setenv('LIVE_PAPER_EVENT_HISTORY_LIMIT', '7')
    assert LivePaperSettings().enabled is False and LivePaperSettings().event_history_limit == 7
    with pytest.raises(ValidationError):
        config.enabled = False
    with pytest.raises(ValidationError):
        LivePaperSettings(extra_key=1)
    with pytest.raises(ValidationError):
        LivePaperSettings.model_validate(config.model_copy(update={'queue_limit': 0}))


@pytest.mark.parametrize('value', ['yes', '1', 1, 0, None])
def test_explicit_boolean_only(value):
    with pytest.raises(ValidationError):
        LivePaperSettings(enabled=value)


def test_events_are_safe_frozen_and_utc_aware():
    event = LivePaperEvent(event_id='event_test', timestamp=START, category='batch',
        severity='warning', reason='missing_symbol', explanation='A required public candle is missing.')
    assert event.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        event.explanation = 'changed'
    for change in ({'timestamp': START.replace(tzinfo=None)}, {'explanation': 'x'*501},
                   {'severity': 'secret'}, {'reason': 'arbitrary trace!'}, {'account_id': 'anything'}):
        with pytest.raises(ValidationError):
            LivePaperEvent.model_validate(event.model_dump() | change)
    assert {status.value for status in LivePaperStatus} == {
        'DISABLED', 'STARTING', 'WARMING_UP', 'RUNNING', 'DEGRADED', 'STOPPING', 'STOPPED', 'ERROR'}


def test_all_equal_time_permutations_identical():
    expected = None
    for ordering in permutations(SYMBOLS):
        batcher, timer = make_batcher()
        output = []
        for symbol in ordering:
            event = bar(symbol=symbol)
            output.extend(batcher.push(event, now=event.received_at).batches)
        assert len(output) == 1
        assert tuple(item.symbol for item in output[0].bars) == SYMBOLS
        assert output[0].reason == 'complete' and output[0].missing_symbols == ()
        encoded = output[0].model_dump_json()
        expected = encoded if expected is None else expected
        assert encoded == expected and batcher.pending_count == 0


def test_timeout_exact_boundary_missing_stays_missing_and_late_cannot_rewrite():
    batcher, timer = make_batcher()
    event = bar()
    assert not batcher.push(event, now=event.received_at).batches
    timer.value = 1.499
    assert not batcher.poll().batches
    timer.value = 1.5
    batch = batcher.poll().batches[0]
    before = batch.model_dump_json()
    assert batch.reason == 'timeout' and batch.missing_symbols == ('ETHUSDT', 'SOLUSDT')
    late = batcher.push(bar(symbol='ETHUSDT'), now=event.received_at)
    assert late.notices[0].reason == 'late_bar' and not late.batches
    assert batch.model_dump_json() == before and not batcher.poll().batches


def test_identical_duplicates_ignore_publication_receipt_differences():
    batcher, timer = make_batcher()
    first = bar()
    batcher.push(first, now=first.received_at)
    later = first.model_copy(update={'event_time': first.event_time+timedelta(milliseconds=10),
                                     'received_at': first.received_at+timedelta(milliseconds=20)})
    assert canonical_bar(first) == canonical_bar(later)
    assert batcher.push(later, now=later.received_at).notices[0].reason == 'duplicate_bar'
    timer.value = 2
    batcher.poll()
    assert batcher.push(later, now=later.received_at).notices[0].reason == 'duplicate_bar'


def test_conflicting_pending_bar_is_excluded_for_all_arrival_orders():
    for prices in permutations(('101', '102')):
        batcher, timer = make_batcher(('BTCUSDT', 'ETHUSDT'))
        for price in prices:
            event = bar(closed=price)
            result = batcher.push(event, now=event.received_at)
        assert result.notices[0].reason == 'conflicting_bar'
        other = bar(symbol='ETHUSDT')
        group = batcher.push(other, now=other.received_at).batches[0]
        assert group.reason == 'conflict' and group.conflicting_symbols == ('BTCUSDT',)
        assert group.missing_symbols == ('BTCUSDT',) and len(group.bars) == 1


def test_conflicting_late_bar_never_replaces_finalized_bar():
    batcher, timer = make_batcher(('BTCUSDT',))
    first = bar()
    group = batcher.push(first, now=first.received_at).batches[0]
    result = batcher.push(bar(closed='110'), now=first.received_at)
    assert result.notices[0].reason == 'conflicting_late_bar' and not result.batches
    assert group.bars[0].close == 101


def test_newer_complete_group_waits_for_older_pending_group():
    batcher, timer = make_batcher(('BTCUSDT', 'ETHUSDT'))
    batcher.push(bar(), now=bar().received_at)
    for symbol in ('BTCUSDT', 'ETHUSDT'):
        event = bar(1, symbol=symbol)
        assert not batcher.push(event, now=event.received_at).batches
    timer.value = 1.5
    batches = batcher.poll().batches
    assert [item.boundary for item in batches] == [START+timedelta(minutes=1), START+timedelta(minutes=2)]
    assert [item.reason for item in batches] == ['timeout', 'complete']


def test_pending_and_sealed_buffers_bounded():
    batcher, timer = make_batcher(('BTCUSDT', 'ETHUSDT'), pending_batch_limit=2)
    for index in range(2):
        event = bar(index)
        batcher.push(event, now=event.received_at)
    event = bar(2)
    assert batcher.push(event, now=event.received_at).notices[0].reason == 'batch_buffer_full'
    assert batcher.pending_count == 2
    timer.value = 2
    assert len(batcher.poll().batches) == 2
    for index in range(2, 100):
        for symbol in ('ETHUSDT', 'BTCUSDT'):
            event = bar(index, symbol=symbol)
            batcher.push(event, now=event.received_at)
        assert batcher.retained_fingerprint_count <= 4
    assert batcher.push(bar(), now=event.received_at).notices[0].reason == 'late_bar'


def test_discard_seals_loss_windows():
    batcher, timer = make_batcher()
    event = bar()
    batcher.push(event, now=event.received_at)
    batcher.discard_pending()
    assert batcher.pending_count == 0
    assert batcher.push(event, now=event.received_at).notices[0].reason == 'late_bar'


@pytest.mark.parametrize('change,reason', [
    ({'is_closed': False}, 'unfinished_candle'),
    ({'symbol': 'ADAUSDT'}, 'bar_scope_mismatch'),
    ({'high': 90}, 'invalid_finalized_bar'),
    ({'volume': -1}, 'invalid_finalized_bar'),
    ({'event_time': START}, 'invalid_bar_clock'),
    ({'received_at': START}, 'invalid_bar_clock'),
    ({'close_time': START+timedelta(seconds=30)}, 'invalid_finalized_bar'),
    ({'taker_buy_volume': 99}, 'invalid_finalized_bar'),
])
def test_malformed_open_or_wrong_scope_never_triggers(change, reason):
    batcher, timer = make_batcher(('BTCUSDT',))
    event = bar().model_copy(update=change)
    result = batcher.push(event, now=START+timedelta(minutes=1))
    assert not result.batches and result.notices[0].reason == reason
    assert batcher.pending_count == 0 and batcher.watermark is None


def test_future_receipt_and_naive_clock_rejected():
    batcher, timer = make_batcher()
    assert batcher.push(bar(), now=START).notices[0].reason == 'invalid_bar_clock'
    with pytest.raises(ValueError, match='aware'):
        batcher.push(bar(), now=START.replace(tzinfo=None))


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True])
def test_monotonic_invalid_or_rollback_fails(value):
    batcher, timer = make_batcher()
    batcher.poll()
    timer.value = value
    with pytest.raises(ValueError):
        batcher.poll()


def test_batch_contract_rejects_open_or_incoherent_diagnostics():
    event = bar()
    base = dict(boundary=event.close_time, bars=(event,), reason='complete')
    for changes in ({'bars': (event, event)}, {'bars': (event.model_copy(update={'is_closed': False}),)},
                    {'missing_symbols': ('BTCUSDT',)}, {'conflicting_symbols': ('ETHUSDT',)}):
        with pytest.raises(ValidationError):
            LiveBarBatch(**(base | changes))
