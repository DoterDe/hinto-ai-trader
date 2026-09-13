from decimal import Decimal

import pytest

from backtest_fixtures import bar, historical_decision
from src.application.backtest_settings import BacktestSettings
from src.application.live_paper_portfolio import LivePaperPortfolio
from src.application.live_paper_settings import LivePaperSettings
from src.application.paper_portfolio_ledger import PaperPortfolioLedger
from src.application.paper_portfolio_settings import PaperPortfolioSettings


def ledger(symbols=('BTCUSDT',), horizon=5, **limits):
    return LivePaperPortfolio(symbols, interval='1m', runtime=LivePaperSettings(
        event_history_limit=7, curve_history_limit=9, position_history_limit=3),
        settings=PaperPortfolioSettings(**limits), costs=BacktestSettings(holding_period_bars=horizon))


def advance(book, index, *, decision=False, symbol='BTCUSDT', **fields):
    event = bar(index, symbol=symbol, **fields)
    return book.advance(event.close_time, [event], [historical_decision(event).decision] if decision else ())


@pytest.mark.parametrize('direction,exit_price,expected', [('LONG', '110', '985.3001'), ('SHORT', '90', '986.7001')])
def test_next_open_fixed_horizon_and_phase7_accounting(direction, exit_price, expected):
    book = ledger()
    event = bar()
    book.advance(event.close_time, [event], [historical_decision(event, direction=direction).decision])
    assert len(book.pending) == 1 and not book.active
    advance(book, 1, closed=exit_price)
    assert book.active['BTCUSDT'].entry_time == bar(1).open_time
    assert book.active['BTCUSDT'].entry_price_raw == 100
    for index in range(2, 6):
        advance(book, index, closed=exit_price)
    assert len(book.closes) == 1 and not book.active and not book.pending
    assert book.closes[0].close.exit_time == bar(5).close_time
    assert book.closed_pnl.net_pnl == Decimal(expected)
    assert book.state(bar(5).close_time).realized_equity == Decimal(100000)+Decimal(expected)


def test_horizon_one_and_same_close_capacity_released():
    book = ledger(horizon=1)
    advance(book, 0, decision=True)
    advance(book, 1, decision=True)
    assert book.completed_count == 1 and len(book.pending) == 1
    assert book.curve[-1].open_count_before_exits == 1
    assert book.curve[-1].state.open_count == 0


def test_same_symbol_and_opposite_signal_do_not_reverse():
    book = ledger()
    advance(book, 0, decision=True)
    event = bar(1)
    result = book.advance(event.close_time, [event], [historical_decision(event, direction='SHORT').decision])
    assert result[0].reason == 'symbol_position_active'
    assert book.active['BTCUSDT'].reservation.direction == 'LONG'


def test_missing_entry_expires_without_position():
    book = ledger()
    advance(book, 0, decision=True)
    book.advance(bar(1).close_time, [])
    assert book.expired_count == 1 and not book.pending and not book.active
    assert book.state(bar(1).close_time).marked_equity == 100000


def test_missing_horizon_unknown_forever_without_rewriting_curve():
    book = ledger()
    advance(book, 0, decision=True)
    advance(book, 1)
    previous = book.curve[-1].model_dump_json()
    book.advance(bar(2).close_time, [])
    assert book.active['BTCUSDT'].status == 'INCOMPLETE'
    assert book.positions()[0].unrealized_net_pnl is None
    assert book.state(bar(2).close_time).marked_equity is None
    assert book.curve[-2].model_dump_json() == previous
    result = advance(book, 3, decision=True)
    assert result[0].reason == 'invalid_or_stale_portfolio_state' and not book.closes


def test_invalidate_on_queue_loss_preserves_unresolved_notional():
    book = ledger()
    advance(book, 0, decision=True)
    advance(book, 1)
    book.invalidate()
    state = book.state(bar(1).close_time)
    assert state.marked_equity is None and state.open_notional == 10000
    assert not book.evidence and not book.marks


@pytest.mark.parametrize('limits,reason', [
    ({'max_open_positions': 1}, 'max_open_positions'),
    ({'max_gross_exposure_fraction': '.15'}, 'gross_exposure_limit'),
    ({'max_symbol_exposure_fraction': '.05'}, 'symbol_exposure_limit'),
])
def test_reuses_phase7_capacity_rules(limits, reason):
    book = ledger(('BTCUSDT', 'ETHUSDT'), **limits)
    bars = [bar(symbol=symbol) for symbol in book.symbols]
    results = book.advance(bars[0].close_time, bars, [historical_decision(event).decision for event in reversed(bars)])
    assert results[-1].reason == reason


def test_equivalent_finite_prefix_matches_phase7_ledger_exactly():
    live = ledger()
    old = PaperPortfolioLedger(symbols=('BTCUSDT',))
    for index in range(7):
        event = bar(index)
        observations = [historical_decision(event)]
        expected = old.advance([event], observations)
        actual = live.advance(event.close_time, [event], [item.decision for item in observations])
        assert actual == expected
        assert live.curve[-1] == old.curve[-1]
    assert live.closes[-1].close == old.closes[-1]


def test_long_stream_bounds_and_lifetime_pnl_survive_eviction():
    book = ledger(horizon=1)
    for index in range(400):
        advance(book, index, decision=True)
        assert len(book.pending)+len(book.active) <= 1
        assert len(book.closes) <= 3 and len(book.curve) <= 9 and book.seen_count <= 7
        assert len(book.evidence) <= 1
    assert book.completed_count == 399 and len(book.closes) == 3
    assert book.closed_pnl.net_pnl > sum(item.close.pnl.net_pnl for item in book.closes)


def test_duplicate_identity_never_double_reserves():
    book = ledger()
    event = bar()
    decision = historical_decision(event).decision
    result = book.advance(event.close_time, [event], [decision, decision])
    assert len(result) == 1 and book.duplicate_count == 1 and len(book.pending) == 1


def test_invalid_transition_prevents_resume_and_exposes_unknown():
    book = ledger()
    advance(book, 0)
    with pytest.raises(ValueError):
        advance(book, 0)
    with pytest.raises(RuntimeError):
        advance(book, 1)
    assert book.state(bar(1).close_time).marked_equity is None
