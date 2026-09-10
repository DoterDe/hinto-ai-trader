from decimal import Decimal, localcontext

import pytest

from portfolio_fixtures import START, state
from src.application.backtest_settings import BacktestSettings
from src.application.paper_portfolio_identity import portfolio_policy_identity
from src.application.paper_portfolio_math import capacity_reason, closed_pnl, desired_notional, marked_pnl
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.paper_portfolio import PaperEntryReservation, PaperExposure, PaperPnl, PaperPortfolioState


def reservation(**updates):
    return PaperEntryReservation(**(dict(reservation_id="reservation_test", decision_id="decision_test",
        symbol="BTCUSDT", direction="LONG", virtual_notional=10000, decision_time=START,
        expected_entry_time=START, policy_id="policy_test") | updates))


def test_defaults_frozen_models_and_roundtrip():
    settings = PaperPortfolioSettings()
    assert settings.model_dump() == dict(initial_virtual_equity=Decimal(100000), target_position_fraction=Decimal('.10'),
        max_gross_exposure_fraction=Decimal('.40'), max_symbol_exposure_fraction=Decimal('.15'),
        max_open_positions=4, max_drawdown_fraction=Decimal('.20'), one_position_per_symbol=True)
    for item, field in ((settings, 'initial_virtual_equity'), (reservation(), 'virtual_notional'), (state(), 'realized_equity')):
        with pytest.raises(ValueError):
            setattr(item, field, 1)
        assert type(item).model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize('field', ['initial_virtual_equity', 'target_position_fraction', 'max_gross_exposure_fraction',
    'max_symbol_exposure_fraction', 'max_drawdown_fraction'])
@pytest.mark.parametrize('value', [0, -1, True, 'NaN', 'Infinity', '-Infinity'])
def test_bad_numeric_settings(field, value):
    with pytest.raises(ValueError):
        PaperPortfolioSettings(**{field: value})


@pytest.mark.parametrize('updates', [dict(target_position_fraction='1.01'), dict(max_gross_exposure_fraction='1.01'),
    dict(max_symbol_exposure_fraction='.41'), dict(max_drawdown_fraction=1), dict(max_open_positions=0),
    dict(max_open_positions=True), dict(max_open_positions=1.5), dict(one_position_per_symbol=1),
    dict(one_position_per_symbol='yes'), dict(one_position_per_symbol=False), dict(optimizer=True)])
def test_unsupported_or_incoherent_settings(updates):
    with pytest.raises(ValueError):
        PaperPortfolioSettings(**updates)


def test_environment_is_explicit_and_unsafe_copies_revalidated(monkeypatch):
    monkeypatch.setenv('PORTFOLIO_MAX_OPEN_POSITIONS', '3')
    monkeypatch.setenv('PORTFOLIO_TARGET_POSITION_FRACTION', '0.125')
    monkeypatch.setenv('PORTFOLIO_ONE_POSITION_PER_SYMBOL', 'TRUE')
    settings = PaperPortfolioSettings()
    assert settings.max_open_positions == 3 and settings.target_position_fraction == Decimal('.125')
    with pytest.raises(ValueError):
        PaperPortfolioSettings.model_validate(settings.model_copy(update={'max_open_positions': True}))
    monkeypatch.setenv('PORTFOLIO_ONE_POSITION_PER_SYMBOL', 'false')
    with pytest.raises(ValueError, match='unsupported'):
        PaperPortfolioSettings()


def test_identity_is_canonical_and_sensitive_to_settings():
    first = portfolio_policy_identity(PaperPortfolioSettings())
    assert first == portfolio_policy_identity(PaperPortfolioSettings(target_position_fraction='.1000'))
    assert first != portfolio_policy_identity(PaperPortfolioSettings(target_position_fraction='.11'))


@pytest.mark.parametrize('field', ['quantity', 'account', 'balance', 'leverage', 'margin', 'order_id', 'api_key'])
def test_reservations_have_no_execution_fields(field):
    with pytest.raises(ValueError):
        reservation(**{field: 1})


@pytest.mark.parametrize('updates', [dict(virtual_notional=0), dict(virtual_notional='NaN'), dict(direction='BUY'),
    dict(decision_time=START.replace(tzinfo=None)), dict(expected_entry_time=START.replace(year=2021))])
def test_invalid_reservation_contract(updates):
    with pytest.raises(ValueError):
        reservation(**updates)


def test_sizing_equity_exposure_and_exact_drawdown():
    snapshot = state('100000', unrealized='-20000', exposures=(
        PaperExposure(symbol='BTCUSDT', open_notional=10000, open_count=1),
        PaperExposure(symbol='ETHUSDT', reserved_notional=5000, reservation_count=1)))
    assert snapshot.marked_equity == 80000 and snapshot.drawdown == Decimal('.2')
    assert snapshot.gross_exposure == 15000 and snapshot.gross_exposure_fraction == Decimal('.1875')
    assert snapshot.open_count == snapshot.reservation_count == 1
    assert desired_notional(snapshot.marked_equity, PaperPortfolioSettings()) == 8000
    assert capacity_reason(snapshot, 'SOLUSDT', Decimal(8000), PaperPortfolioSettings()) == 'portfolio_drawdown_limit'
    assert state('80000.01').drawdown < Decimal('.2')
    assert state('-1000').marked_equity == -1000 and state('-1000').drawdown == Decimal('1.01')
    assert state('-1000').gross_exposure_fraction is None
    assert state(unrealized=None).marked_equity is state(unrealized=None).drawdown is None


def test_capacity_is_all_or_none_with_inclusive_boundary():
    settings = PaperPortfolioSettings()
    exposure = PaperExposure(symbol='ETHUSDT', reserved_notional=30000, reservation_count=3)
    snapshot = state(exposures=(exposure,))
    assert capacity_reason(snapshot, 'BTCUSDT', Decimal(10000), settings) is None
    assert capacity_reason(snapshot, 'BTCUSDT', Decimal('10000.01'), settings) == 'gross_exposure_limit'
    assert capacity_reason(state(), 'BTCUSDT', Decimal(15000), settings) is None
    assert capacity_reason(state(), 'BTCUSDT', Decimal('15000.01'), settings) == 'symbol_exposure_limit'


@pytest.mark.parametrize('field', ['realized_equity', 'unrealized_net_pnl', 'marked_equity', 'peak_equity',
    'drawdown', 'open_notional', 'reserved_notional', 'gross_exposure', 'gross_exposure_fraction'])
@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_state_copies_rejected(field, value):
    with pytest.raises(ValueError):
        PaperPortfolioState.model_validate(state().model_copy(update={field: Decimal(value)}))


@pytest.mark.parametrize('updates', [dict(marked_equity=1), dict(drawdown=1), dict(gross_exposure=1),
    dict(open_count=1), dict(peak_equity=90000), dict(unrealized_net_pnl=None)])
def test_state_must_reconcile(updates):
    with pytest.raises(ValueError):
        PaperPortfolioState.model_validate(state().model_copy(update=updates))


@pytest.mark.parametrize('direction,price,gross,fee,slip,net', [
    ('LONG', 110, '1000', '5.001', '2', '992.999'),
    ('SHORT', 90, '1000', '4.999', '2', '993.001'),
    ('LONG', 90, '-1000', '5.001', '2', '-1007.001'),
    ('SHORT', 110, '-1000', '4.999', '2', '-1006.999'),
    ('LONG', 100, '0', '5.001', '2', '-7.001'),
    ('SHORT', 100, '0', '4.999', '2', '-6.999'),
])
def test_independent_entry_only_mark_costs(direction, price, gross, fee, slip, net):
    result = marked_pnl(10000, 100, price, direction, BacktestSettings())
    assert result.gross_pnl == Decimal(gross)
    assert result.fee_cost == Decimal(fee) and result.slippage_cost == Decimal(slip)
    assert result.net_pnl == Decimal(net)
    assert result.total_cost == Decimal(fee) + Decimal(slip)


@pytest.mark.parametrize('direction,exit,net,fee,slip', [
    ('LONG', 110, '985.3001', '10.4999', '4.2'),
    ('SHORT', 90, '986.7001', '9.4999', '3.8'),
    ('SHORT', 110, '-1014.7001', '10.5001', '4.2')])
def test_closed_pnl_reuses_two_sided_phase6_costs(direction, exit, net, fee, slip):
    result = closed_pnl(10000, 100, exit, direction, BacktestSettings())
    assert result.net_pnl == Decimal(net)
    assert result.fee_cost == Decimal(fee) and result.slippage_cost == Decimal(slip)


@pytest.mark.parametrize('values', [(0, 100, 100, 'LONG'), (1, 0, 100, 'LONG'), (1, 100, 0, 'LONG'),
    (1, 100, 'Infinity', 'LONG'), (1, 100, 100, 'NEUTRAL'), (True, 100, 100, 'SHORT')])
def test_invalid_mark_inputs(values):
    with pytest.raises(ValueError):
        marked_pnl(*values, BacktestSettings())


def test_numeric_context_is_restored_and_independent():
    with localcontext() as context:
        context.prec = 4
        context.rounding = 'ROUND_DOWN'
        assert marked_pnl(10000, 100, 110, 'LONG', BacktestSettings()).net_pnl == Decimal('992.999')
        assert closed_pnl(10000, 100, 110, 'LONG', BacktestSettings()).net_pnl == Decimal('985.3001')
        assert context.prec == 4 and context.rounding == 'ROUND_DOWN'


@pytest.mark.parametrize('field', ['total_cost', 'net_pnl'])
def test_inconsistent_pnl_components_fail(field):
    result = PaperPnl(gross_pnl=10, fee_cost=2, slippage_cost=1, total_cost=3, net_pnl=7)
    with pytest.raises(ValueError, match='reconcile'):
        PaperPnl.model_validate(result.model_copy(update={field: Decimal(99)}))


def test_pnl_reconciliation_preserves_phase6_rounding_and_rejects_overflow():
    result = closed_pnl(Decimal('10000.33333333333333333333333333333'), 103, 117, 'LONG', BacktestSettings())
    assert PaperPnl.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValueError):
        closed_pnl(Decimal('1e999999'), Decimal('1e-999999'), 100, 'SHORT', BacktestSettings())
