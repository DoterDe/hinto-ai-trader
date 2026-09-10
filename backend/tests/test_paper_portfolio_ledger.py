from datetime import timedelta
from decimal import Decimal

import pytest

from backtest_fixtures import START, bar, historical_decision
from src.application.backtest_settings import BacktestSettings
from src.application.paper_portfolio_ledger import PaperPortfolioLedger
from src.application.paper_portfolio_settings import PaperPortfolioSettings


def ledger(horizon=2, *, settings=None, fee=5, slip=2):
    return PaperPortfolioLedger(symbols=('BTCUSDT', 'ETHUSDT'), settings=settings,
        backtest_settings=BacktestSettings(holding_period_bars=horizon, fee_bps_per_side=fee, slippage_bps_per_side=slip))


def reserve(engine, source=None, **kwargs):
    source = source or bar(closed='300')
    records = engine.advance((source,), (historical_decision(source, **kwargs),))
    assert records[0].action == 'RESERVED'
    return records[0]


@pytest.mark.parametrize('direction,net,mark', [('LONG', '985.3001', '492.999'), ('SHORT', '-1014.7001', '-506.999')])
def test_exact_next_open_horizon_costs_and_equity(direction, net, mark):
    engine = ledger()
    reserve(engine, direction=direction)
    assert engine.positions == () and engine.curve[-1].state.reserved_notional == 10000
    engine.advance((bar(1, opened='100', closed='105'),))
    position, = engine.positions
    assert position.entry_price_raw == 100 and position.entry_time == START + timedelta(minutes=1)
    assert position.bars_held == 1 and position.status == 'OPEN'
    assert engine.curve[-1].state.realized_equity == 100000
    assert engine.curve[-1].state.marked_equity == 100000 + Decimal(mark)
    assert not engine.closes
    engine.advance((bar(2, opened='105', closed='110'),))
    close, = engine.closes
    assert close.exit_time == START + timedelta(minutes=3) and close.exit_price_raw == 110
    assert close.pnl.net_pnl == Decimal(net)
    final = engine.finish()
    assert final.marked_equity == final.realized_equity == 100000 + Decimal(net)
    assert final.open_count == final.reservation_count == 0
    assert engine.positions[0].status == 'CLOSED' and engine.finish() == final


@pytest.mark.parametrize('direction,price', [('LONG', '110'), ('SHORT', '90')])
def test_h1_symmetric_zero_cost_pnl_and_intrastep_position_count(direction, price):
    engine = ledger(1, fee=0, slip=0)
    reserve(engine, direction=direction)
    engine.advance((bar(1, opened='100', closed=price),))
    assert engine.closes[0].pnl.net_pnl == 1000
    assert engine.curve[-1].state.open_count == 0
    assert engine.curve[-1].open_count_before_exits == 1


def test_default_horizon_is_five_complete_bars():
    engine = ledger(5)
    reserve(engine)
    for index in range(1, 5):
        engine.advance((bar(index),))
        assert not engine.closes
    engine.advance((bar(5),))
    assert engine.positions[0].bars_held == 5
    assert engine.closes[0].exit_time == START + timedelta(minutes=6)


def test_missing_entry_releases_capacity_and_never_opens_later():
    engine = ledger()
    reserve(engine)
    source = bar(2)
    records = engine.advance((source,), (historical_decision(source),))
    assert records[0].action == 'RESERVED'
    assert engine.positions == ()
    assert engine.expiries[0].reason == 'missing_entry_bar'
    assert engine.curve[-1].state.reservation_count == 1


def test_symbol_absent_from_complete_timestamp_expires_reservation():
    engine = ledger()
    reserve(engine)
    engine.advance((bar(1, symbol='ETHUSDT'),))
    assert engine.expiries[0].reason == 'missing_entry_bar'
    assert engine.curve[-1].state.gross_exposure == 0 and not engine.positions


def test_pending_dataset_end_is_explicit_and_does_not_rewrite_curve():
    engine = ledger()
    reserve(engine)
    before = engine.curve
    final = engine.finish()
    assert final.gross_exposure == 0 and final.marked_equity == 100000
    assert engine.expiries[0].reason == 'dataset_ended'
    assert engine.positions == () and engine.curve == before


def test_open_dataset_end_has_unresolved_notional_no_exit_or_final_mark():
    engine = ledger(5)
    reserve(engine)
    engine.advance((bar(1),))
    before = engine.curve
    final = engine.finish()
    assert final.marked_equity is final.drawdown is final.gross_exposure_fraction is None
    assert final.realized_equity == 100000 and final.open_notional == 10000
    assert engine.positions[0].status == 'INCOMPLETE' and engine.positions[0].reason == 'dataset_ended'
    assert not engine.closes and engine.curve == before


def test_gap_invalidates_open_mark_and_blocks_new_reservations_permanently():
    engine = ledger(5)
    reserve(engine)
    engine.advance((bar(1),))
    source = bar(3, symbol='ETHUSDT')
    records = engine.advance((source,), (historical_decision(source),))
    assert records[0].reason == 'invalid_or_stale_portfolio_state'
    assert engine.positions[0].reason == 'missing_horizon_bar'
    assert engine.curve[-1].state.marked_equity is None
    engine.advance((bar(4), bar(4, symbol='ETHUSDT')))
    assert engine.finish().marked_equity is None and not engine.closes


def test_other_positions_can_finish_after_one_symbol_gap():
    engine = ledger(2, fee=0, slip=0)
    sources = (bar(), bar(symbol='ETHUSDT'))
    engine.advance(sources, tuple(historical_decision(item) for item in sources))
    engine.advance((bar(1), bar(1, symbol='ETHUSDT')))
    engine.advance((bar(2, symbol='ETHUSDT', opened='100', closed='110'),))
    assert len(engine.closes) == 1 and engine.closes[0].pnl.net_pnl == 1000
    final = engine.finish()
    assert final.realized_equity == 101000 and final.marked_equity is None
    assert final.open_count == 1


def test_same_symbol_signals_do_not_pyramid_or_reverse_and_exits_precede_arbitration():
    engine = ledger(2)
    reserve(engine)
    source = bar(1)
    records = engine.advance((source,), (historical_decision(source, direction='SHORT'),))
    assert records[0].reason == 'symbol_position_active'
    source = bar(2)
    records = engine.advance((source,), (historical_decision(source, direction='SHORT'),))
    assert records[0].action == 'RESERVED'
    assert len(engine.positions) == len(engine.closes) == 1
    assert engine.curve[-1].state.open_count == 0 and engine.curve[-1].state.reservation_count == 1


def test_drawdown_gate_does_not_force_close_and_recovers_with_mark():
    settings = PaperPortfolioSettings(target_position_fraction='.4', max_symbol_exposure_fraction='.4')
    engine = ledger(3, settings=settings, fee=0, slip=0)
    reserve(engine)
    sources = (bar(1, opened='100', closed='50'), bar(1, symbol='ETHUSDT'))
    records = engine.advance(sources, (historical_decision(sources[1]),))
    assert engine.curve[-1].state.drawdown == Decimal('.2')
    assert records[0].reason == 'portfolio_drawdown_limit' and not engine.closes
    sources = (bar(2, opened='50', closed='100'), bar(2, symbol='ETHUSDT'))
    records = engine.advance(sources, (historical_decision(sources[1]),))
    assert engine.curve[-1].state.drawdown == 0
    assert records[0].reason == 'gross_exposure_limit'  # recovered drawdown, but existing capacity stays occupied
    engine.advance((bar(3),))
    assert len(engine.closes) == 1


def test_short_loss_can_make_equity_nonpositive_without_clamping_or_liquidation():
    settings = PaperPortfolioSettings(target_position_fraction='.4', max_symbol_exposure_fraction='.4')
    engine = ledger(2, settings=settings, fee=0, slip=0)
    reserve(engine, direction='SHORT')
    sources = (bar(1, opened='100', closed='400'), bar(1, symbol='ETHUSDT'))
    records = engine.advance(sources, (historical_decision(sources[1]),))
    assert engine.curve[-1].state.marked_equity == -20000
    assert engine.curve[-1].state.drawdown == Decimal('1.2')
    assert records[0].reason == 'nonpositive_equity' and not engine.closes
    engine.advance((bar(2, opened='400', closed='400'),))
    assert engine.finish().realized_equity == -20000


def test_duplicates_count_once_and_ids_are_evidence_sensitive():
    def run(price='110'):
        engine = ledger(1)
        source = bar()
        observed = historical_decision(source)
        engine.advance((source,), (observed, observed))
        engine.advance((bar(1, opened='100', closed=price),))
        engine.finish()
        return engine
    first, second, changed = run(), run(), run('111')
    assert first.decisions == second.decisions and first.reservations == second.reservations
    assert first.positions == second.positions and first.closes == second.closes
    assert first.duplicate_reads == 1 and len(first.reservations) == 1
    assert first.positions[0].position_id != changed.positions[0].position_id
    assert first.closes[0].close_id != changed.closes[0].close_id


def test_empty_and_invalidated_ledger_are_explicit():
    engine = ledger()
    assert engine.finish() is None and engine.curve == ()
    with pytest.raises(RuntimeError):
        engine.advance((bar(),))
    engine = ledger()
    with pytest.raises(ValueError):
        engine.advance((bar(), bar()))
    with pytest.raises(RuntimeError):
        engine.advance((bar(1),))
    with pytest.raises(RuntimeError):
        engine.finish()


@pytest.mark.parametrize('events', [(bar(1), bar()), (bar(symbol='OTHER'),), (bar(), bar(1, symbol='ETHUSDT'))])
def test_malformed_scope_or_mixed_time_group_rejected(events):
    with pytest.raises(ValueError):
        ledger().advance(events)


def test_monthly_horizon_and_gaps_use_calendar_boundaries():
    def month(number):
        opened, end = START.replace(month=number), START.replace(month=number+1)
        return bar(number, interval='1M', open_time=opened, close_time=end, event_time=end, received_at=end)
    engine = PaperPortfolioLedger(symbols=('BTCUSDT',), interval='1M', backtest_settings=BacktestSettings(holding_period_bars=2))
    engine.advance((month(1),), (historical_decision(month(1)),))
    engine.advance((month(2),))
    assert not engine.closes
    engine.advance((month(3),))
    assert engine.positions[0].entry_time == START.replace(month=2)
    assert engine.closes[0].exit_time == START.replace(month=4)
