from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from backtest_fixtures import START, bar, historical_decision
from portfolio_fixtures import decision, state
from src.application.backtest_settings import BacktestSettings
from src.application.paper_portfolio_ledger import PaperPortfolioLedger
from src.application.paper_portfolio_metrics import portfolio_metrics
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.paper_portfolio import (
    PaperEntryReservation, PaperExposure, PaperPnl, PaperPortfolioCurvePoint, PaperPosition,
    PaperPositionClose, PortfolioDecisionRecord,
)


def independent_artifacts():
    """Hand-built two-position history: 1000 -> 1250 -> 1000, with costs of 20."""
    records, reservations, positions, closes = [], [], [], []
    for index, (symbol, gross, net, direction, exit_price) in enumerate((
        ('BTCUSDT', 260, 250, 'LONG', 360), ('ETHUSDT', -240, -250, 'SHORT', 340))):
        source = decision(index, symbol=symbol, direction=direction)
        reservation = PaperEntryReservation(reservation_id=f'r{index}', decision_id=source.decision_id,
            symbol=symbol, direction=direction, virtual_notional=100, decision_time=source.generated_at,
            expected_entry_time=source.generated_at, policy_id='policy_test')
        record = PortfolioDecisionRecord(portfolio_decision_id=f'd{index}', upstream=source, policy_id='policy_test',
            state_id=f's{index}', evaluated_at=source.generated_at, action='RESERVED', reason='capacity_reserved',
            desired_notional=100, reservation_id=reservation.reservation_id)
        exit_time = source.generated_at + timedelta(minutes=1)
        position = PaperPosition(position_id=f'p{index}', reservation=reservation, interval='1m',
            entry_time=source.generated_at, entry_price_raw=100, holding_period_bars=1, bars_held=1,
            expected_next_open=exit_time, backtest_settings_id='costs_test', status='CLOSED', reason='horizon_completed',
            last_mark_time=exit_time, last_mark_price=exit_price)
        close = PaperPositionClose(close_id=f'c{index}', position_id=position.position_id, exit_time=exit_time,
            exit_price_raw=exit_price, pnl=PaperPnl(gross_pnl=gross, fee_cost=10, slippage_cost=0, total_cost=10, net_pnl=net))
        records.append(record)
        reservations.append(reservation)
        positions.append(position)
        closes.append(close)
    zero = PaperPnl(gross_pnl=0, fee_cost=0, slippage_cost=0, total_cost=0, net_pnl=0)
    first = PaperPnl(gross_pnl=260, fee_cost=10, slippage_cost=0, total_cost=10, net_pnl=250)
    final_pnl = PaperPnl(gross_pnl=20, fee_cost=20, slippage_cost=0, total_cost=20, net_pnl=0)
    final = state('1000', peak='1250', timestamp=START+timedelta(minutes=3))
    curve = (
        PaperPortfolioCurvePoint(state=state('1000', peak='1000'), cumulative_closed_pnl=zero, open_count_before_exits=0),
        PaperPortfolioCurvePoint(state=state('1000', peak='1000', timestamp=START+timedelta(minutes=1), exposures=(
            PaperExposure(symbol='BTCUSDT', reserved_notional=100, reservation_count=1),)), cumulative_closed_pnl=zero, open_count_before_exits=0),
        PaperPortfolioCurvePoint(state=state('1250', peak='1250', timestamp=START+timedelta(minutes=2), exposures=(
            PaperExposure(symbol='ETHUSDT', reserved_notional=100, reservation_count=1),)), cumulative_closed_pnl=first, open_count_before_exits=1),
        PaperPortfolioCurvePoint(state=final, cumulative_closed_pnl=final_pnl, open_count_before_exits=1))
    return dict(initial_equity=Decimal(1000), input_count=4, decisions=tuple(records), reservations=tuple(reservations),
        expiries=(), positions=tuple(positions), closes=tuple(closes), curve=curve, final_state=final,
        backtest_settings=BacktestSettings(), symbols=('BTCUSDT', 'ETHUSDT'))


def measured(engine, count):
    final = engine.finish()
    return portfolio_metrics(initial_equity=engine.policy.settings.initial_virtual_equity, input_count=count,
        decisions=engine.decisions, reservations=engine.reservations, positions=engine.positions, closes=engine.closes,
        expiries=engine.expiries, curve=engine.curve, final_state=final, backtest_settings=engine.backtest_settings,
        symbols=engine.symbols)


def test_independent_equity_cost_drawdown_exposure_turnover_and_counts():
    result = portfolio_metrics(**independent_artifacts())
    assert result.input_bar_count == 4 and result.evaluated_decision_count == 2
    assert result.upstream_eligible_count == result.reserved_count == result.opened_count == result.completed_count == 2
    assert result.incomplete_count == result.rejected_count == result.missing_entry_reservation_count == 0
    assert result.long_opened_count == result.short_opened_count == 1
    assert result.final_realized_equity == result.final_marked_equity == 1000
    assert result.total_closed_pnl.gross_pnl == 20 and result.total_closed_pnl.total_cost == 20
    assert result.total_closed_pnl.fee_cost == 20 and result.total_closed_pnl.slippage_cost == 0
    assert result.total_closed_pnl.net_pnl == result.realized_total_return == 0
    assert result.peak_equity == 1250 and result.max_drawdown == Decimal('.2')
    assert result.max_gross_exposure == 100 and result.max_observed_gross_exposure_fraction == Decimal('.1')
    assert result.max_simultaneous_open_positions == 1 and result.average_open_count == 0
    assert result.turnover == Decimal('.2')
    assert result.win_count == result.loss_count == 1 and result.flat_count == 0
    assert result.win_rate == Decimal('.5') and result.valuation_complete
    assert [item.closed_pnl.net_pnl for item in result.per_symbol] == [250, -250]


def test_metrics_container_order_and_ambient_precision_do_not_change_results():
    arguments = independent_artifacts()
    first = portfolio_metrics(**arguments)
    for name in ('decisions', 'reservations', 'positions', 'closes'):
        arguments[name] = tuple(reversed(arguments[name]))
    with localcontext() as context:
        context.prec = 4
        assert portfolio_metrics(**arguments) == first
        assert context.prec == 4


@pytest.mark.parametrize('field', ['decisions', 'reservations', 'positions', 'closes'])
def test_duplicate_artifacts_are_rejected(field):
    arguments = independent_artifacts()
    arguments[field] += arguments[field][:1]
    with pytest.raises(ValueError):
        portfolio_metrics(**arguments)


def test_inconsistent_provenance_curve_or_missing_close_is_rejected():
    for field, replacement in (
        ('closes', ()), ('reservations', ()), ('final_state', state('999', peak='1250', timestamp=START+timedelta(minutes=3))),
        ('curve', tuple(reversed(independent_artifacts()['curve'])))):
        arguments = independent_artifacts()
        arguments[field] = replacement
        with pytest.raises(ValueError):
            portfolio_metrics(**arguments)


def test_empty_dataset_has_initial_equity_no_nan_or_ratio_failure():
    result = measured(PaperPortfolioLedger(symbols=('BTCUSDT',)), 0)
    assert result.final_realized_equity == result.final_marked_equity == 100000
    assert result.input_bar_count == result.opened_count == result.evaluated_decision_count == 0
    assert result.win_rate is None and result.max_drawdown == result.turnover == 0
    assert 'NaN' not in result.model_dump_json() and 'Infinity' not in result.model_dump_json()


def test_no_eligible_and_all_rejected_diagnostics():
    engine = PaperPortfolioLedger(symbols=('BTCUSDT', 'ETHUSDT'), settings=PaperPortfolioSettings(target_position_fraction='.2'))
    engine.advance((bar(),), (historical_decision(bar()),))
    engine.advance((bar(1),), (historical_decision(bar(1), outcome='BLOCKED'),))
    engine.advance((bar(2),), (historical_decision(bar(2), outcome='NO_ACTION'),))
    result = measured(engine, 3)
    assert (result.upstream_eligible_count, result.upstream_blocked_count, result.upstream_no_action_count) == (1, 1, 1)
    assert result.rejected_count == 1 and result.ignored_count == 2
    assert result.opened_count == result.reserved_count == 0
    assert result.rejection_counts[0].reason == 'symbol_exposure_limit' and result.rejection_counts[0].count == 1


def test_incomplete_exposure_keeps_realized_and_entry_costs_separate():
    engine = PaperPortfolioLedger(symbols=('BTCUSDT',))
    engine.advance((bar(),), (historical_decision(bar()),))
    engine.advance((bar(1, opened='100', closed='110'),))
    result = measured(engine, 2)
    assert result.completed_count == 0 and result.incomplete_count == 1
    assert result.final_marked_equity is None and not result.valuation_complete
    assert result.final_realized_equity == 100000 and result.total_closed_pnl.net_pnl == 0
    assert result.outstanding_entry_fee_cost == Decimal('5.001')
    assert result.outstanding_entry_slippage_cost == 2
    assert result.turnover == Decimal('.1') and result.average_open_count == Decimal('.5')


def test_pending_reservations_and_flat_completed_positions():
    engine = PaperPortfolioLedger(symbols=('BTCUSDT',), backtest_settings=BacktestSettings(
        holding_period_bars=1, fee_bps_per_side=0, slippage_bps_per_side=0))
    engine.advance((bar(),), (historical_decision(bar()),))
    engine.advance((bar(1, opened='100', closed='100'),), (historical_decision(bar(1, opened='100', closed='100')),))
    result = measured(engine, 2)
    assert result.reserved_count == 2 and result.opened_count == result.completed_count == 1
    assert result.missing_entry_reservation_count == 1 and result.flat_count == 1
    assert result.win_rate is None and result.max_simultaneous_open_positions == 1


def test_insolvency_is_reported_without_clamping():
    engine = PaperPortfolioLedger(symbols=('BTCUSDT',), settings=PaperPortfolioSettings(
        target_position_fraction='.4', max_symbol_exposure_fraction='.4'), backtest_settings=BacktestSettings(
            holding_period_bars=1, fee_bps_per_side=0, slippage_bps_per_side=0))
    engine.advance((bar(),), (historical_decision(bar(), direction='SHORT'),))
    engine.advance((bar(1, opened='100', closed='400'),))
    result = measured(engine, 2)
    assert result.final_marked_equity == result.final_realized_equity == -20000
    assert result.nonpositive_equity_observed and result.max_drawdown == Decimal('1.2')
    assert result.realized_total_return == Decimal('-1.2')


@pytest.mark.parametrize('price,wins,losses,flats,rate', [
    ('110', 2, 0, 0, Decimal(1)), ('90', 0, 2, 0, Decimal(0)), ('100', 0, 0, 2, None)])
def test_all_winners_losers_or_flats_have_explicit_win_rate(price, wins, losses, flats, rate):
    engine = PaperPortfolioLedger(symbols=('BTCUSDT',), backtest_settings=BacktestSettings(
        holding_period_bars=1, fee_bps_per_side=0, slippage_bps_per_side=0))
    for index in (0, 2):
        source = bar(index)
        engine.advance((source,), (historical_decision(source),))
        engine.advance((bar(index+1, opened='100', closed=price),))
    result = measured(engine, 4)
    assert (result.win_count, result.loss_count, result.flat_count, result.win_rate) == (wins, losses, flats, rate)
