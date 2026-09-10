from datetime import timedelta
from decimal import Decimal
from itertools import permutations

import pytest

from portfolio_fixtures import START, decision, state
from src.application.paper_portfolio_policy import PaperPortfolioPolicy
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.domain.paper_portfolio import PaperExposure

NOW = START + timedelta(minutes=1)


def test_eligible_reserves_without_mutating_upstream_or_state():
    source, before = decision(), state(timestamp=NOW)
    result = PaperPortfolioPolicy().arbitrate((source,), before, now=NOW)
    assert result.decisions[0].action == 'RESERVED'
    assert result.decisions[0].upstream == source
    assert result.reservations[0].virtual_notional == 10000
    assert before.reservation_count == 0 and result.state.reservation_count == 1
    assert result.state.gross_exposure == 10000
    assert result.state.marked_equity == before.marked_equity == 100000
    assert PaperPortfolioPolicy().arbitrate((source,), before, now=NOW) == result


@pytest.mark.parametrize('outcome', ['BLOCKED', 'NO_ACTION'])
def test_noneligible_is_diagnostic_only(outcome):
    result = PaperPortfolioPolicy().evaluate(decision(outcome=outcome), state(timestamp=NOW), now=NOW)
    assert result.action == 'IGNORED' and result.reason == 'decision_not_eligible'
    assert result.reservation_id is result.desired_notional is None


@pytest.mark.parametrize('equity,expected', [('0', 'nonpositive_equity'), ('-1000', 'nonpositive_equity'),
    ('80000', 'portfolio_drawdown_limit'), ('80000.01', 'capacity_reserved')])
def test_equity_and_inclusive_drawdown_gates(equity, expected):
    record = PaperPortfolioPolicy().evaluate(decision(), state(equity, timestamp=NOW), now=NOW)
    assert record.reason == expected


@pytest.mark.parametrize('snapshot', [state(timestamp=START), state(timestamp=NOW+timedelta(seconds=1)),
    state(timestamp=NOW, unrealized=None)])
def test_stale_future_or_unknown_state_rejects(snapshot):
    record = PaperPortfolioPolicy().evaluate(decision(), snapshot, now=NOW)
    assert record.reason == 'invalid_or_stale_portfolio_state' and record.action == 'REJECTED'


def test_old_decision_cannot_be_reused_as_current_eligible():
    later = NOW + timedelta(seconds=1)
    record = PaperPortfolioPolicy().evaluate(decision(), state(timestamp=later), now=later)
    assert record.reason == 'invalid_or_stale_portfolio_state'


@pytest.mark.parametrize('exposure', [PaperExposure(symbol='BTCUSDT', open_notional=10000, open_count=1),
    PaperExposure(symbol='BTCUSDT', reserved_notional=10000, reservation_count=1)])
@pytest.mark.parametrize('direction', ['LONG', 'SHORT'])
def test_existing_symbol_prevents_pyramiding_and_reversal(exposure, direction):
    result = PaperPortfolioPolicy().evaluate(decision(direction=direction), state(timestamp=NOW, exposures=(exposure,)), now=NOW)
    assert result.reason == 'symbol_position_active'


def test_reservations_count_toward_count_and_gross_limits():
    snapshot = state(timestamp=NOW, exposures=(PaperExposure(symbol='ETHUSDT', reserved_notional=30000, reservation_count=1),))
    count = PaperPortfolioPolicy(PaperPortfolioSettings(max_open_positions=1)).evaluate(decision(), snapshot, now=NOW)
    assert count.reason == 'max_open_positions'
    gross = PaperPortfolioPolicy(PaperPortfolioSettings(max_gross_exposure_fraction='.35')).evaluate(decision(), snapshot, now=NOW)
    assert gross.reason == 'gross_exposure_limit' and gross.desired_notional == 10000
    symbol = PaperPortfolioPolicy(PaperPortfolioSettings(target_position_fraction='.16')).evaluate(decision(), state(timestamp=NOW), now=NOW)
    assert symbol.reason == 'symbol_exposure_limit' and symbol.desired_notional == 16000


def test_gross_long_short_notional_does_not_net():
    policy = PaperPortfolioPolicy(PaperPortfolioSettings(max_gross_exposure_fraction='.15'))
    result = policy.arbitrate((decision(), decision(symbol='ETHUSDT', direction='SHORT')), state(timestamp=NOW), now=NOW)
    assert [record.action for record in result.decisions] == ['RESERVED', 'REJECTED']
    assert result.decisions[1].reason == 'gross_exposure_limit'


def test_duplicate_is_explicit_and_same_time_reads_do_not_overbook():
    policy, source = PaperPortfolioPolicy(), decision()
    ignored = policy.evaluate(source, state(timestamp=NOW), now=NOW, duplicate=True)
    assert ignored.action == 'IGNORED' and ignored.reason == 'duplicate_decision'
    result = policy.arbitrate((source, source, source), state(timestamp=NOW), now=NOW)
    assert result.duplicate_reads == 2 and len(result.decisions) == len(result.reservations) == 1
    changed = source.model_copy(update={'observation_id': 'different'})
    with pytest.raises(ValueError, match='conflicting'):
        policy.arbitrate((source, changed), state(timestamp=NOW), now=NOW)


@pytest.mark.parametrize('left,right,winner', [
    ({'composite_score': Decimal(90)}, {'composite_score': Decimal(80)}, 'BTCUSDT'),
    ({'composite_score': Decimal(80)}, {'composite_score': Decimal(-90), 'direction': 'SHORT'}, 'ETHUSDT'),
    ({'confidence': Decimal('.6')}, {'confidence': Decimal('.8')}, 'ETHUSDT'),
    ({'agreement': Decimal('.6')}, {'agreement': Decimal('.8')}, 'ETHUSDT'),
    ({}, {}, 'BTCUSDT'),
])
def test_simultaneous_ranking_boundaries(left, right, winner):
    policy = PaperPortfolioPolicy(PaperPortfolioSettings(max_open_positions=1))
    sources = (decision(**left), decision(symbol='ETHUSDT', **right))
    results = [policy.arbitrate(order, state(timestamp=NOW), now=NOW) for order in permutations(sources)]
    assert results[0] == results[1]
    assert results[0].reservations[0].symbol == winner


def test_final_id_tie_break_and_confidence_does_not_size():
    policy = PaperPortfolioPolicy()
    sources = (decision(decision_id='z'), decision(decision_id='a'))
    result = policy.arbitrate(sources, state(timestamp=NOW), now=NOW)
    assert result.reservations[0].decision_id == 'a' and len(result.reservations) == 1
    low = policy.evaluate(decision(confidence=Decimal('.01')), state(timestamp=NOW), now=NOW)
    high = policy.evaluate(decision(confidence=Decimal(1)), state(timestamp=NOW), now=NOW)
    assert low.desired_notional == high.desired_notional == 10000


def test_four_way_arbitration_permutations_and_capacity():
    sources = tuple(decision(symbol=symbol) for symbol in ('SOLUSDT', 'ETHUSDT', 'BTCUSDT', 'ADAUSDT'))
    policy = PaperPortfolioPolicy(PaperPortfolioSettings(max_open_positions=2))
    results = [policy.arbitrate(order, state(timestamp=NOW), now=NOW) for order in permutations(sources)]
    assert all(result == results[0] for result in results)
    assert [item.symbol for item in results[0].reservations] == ['ADAUSDT', 'BTCUSDT']


@pytest.mark.parametrize('now', [NOW.replace(tzinfo=None), 1])
def test_invalid_clock_fails_closed(now):
    with pytest.raises(ValueError):
        PaperPortfolioPolicy().evaluate(decision(), state(timestamp=NOW), now=now)
    with pytest.raises(ValueError):
        PaperPortfolioPolicy().arbitrate((), state(timestamp=NOW), now=now)


def test_malformed_models_and_mixed_time_batches_fail_closed():
    policy = PaperPortfolioPolicy()
    with pytest.raises(ValueError):
        policy.evaluate(decision().model_copy(update={'confidence': Decimal('NaN')}), state(timestamp=NOW), now=NOW)
    with pytest.raises(ValueError):
        policy.evaluate(decision(), state(timestamp=NOW).model_copy(update={'gross_exposure': -1}), now=NOW)
    with pytest.raises(ValueError, match='timestamp'):
        policy.arbitrate((decision(), decision(1)), state(timestamp=NOW), now=NOW)
