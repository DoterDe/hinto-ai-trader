from datetime import timedelta
from decimal import Decimal

import pytest

from backtest_fixtures import START, bar, historical_decision
from src.application.backtest_evaluator import BacktestEvaluator
from src.application.backtest_settings import BacktestSettings
from src.domain.backtesting import BacktestSignalOutcome


def evaluator(horizon=2, **costs):
    return BacktestEvaluator(symbols=("BTCUSDT", "ETHUSDT"), settings=BacktestSettings(
        holding_period_bars=horizon, **costs))


def start(engine, event=None, **decision):
    event = event or bar()
    assert engine.advance(event) == ()
    observation = historical_decision(event, **decision)
    assert engine.accept(observation)
    return observation


@pytest.mark.parametrize("direction,gross,net", [("LONG", ".1", ".09853001"), ("SHORT", "-.1", "-.10147001")])
def test_next_bar_open_and_exact_fixed_horizon(direction, gross, net):
    engine = evaluator()
    source = bar(closed="300")
    start(engine, source, direction=direction)
    assert engine.advance(bar(1, opened="100", closed="105")) == ()
    result, = engine.advance(bar(2, opened="105", closed="110"))
    assert result.status == "COMPLETED" and result.reason == "horizon_completed"
    assert result.entry_price_raw == 100 and result.exit_price_raw == 110
    assert result.entry_price_raw != source.close
    assert result.decision_time == result.entry_time == START + timedelta(minutes=1)
    assert result.exit_time == START + timedelta(minutes=3)
    assert result.returns.gross_return == Decimal(gross) and result.returns.net_return == Decimal(net)
    assert engine.pending_count == 0 and engine.finish() == ()
    assert BacktestSignalOutcome.model_validate_json(result.model_dump_json()) == result


def test_one_bar_horizon_enters_open_exits_close_of_same_next_bar():
    engine = evaluator(1, fee_bps_per_side=0, slippage_bps_per_side=0)
    start(engine)
    result, = engine.advance(bar(1, opened="100", closed="90"))
    assert result.returns.net_return == Decimal("-.1")
    assert result.entry_time == START + timedelta(minutes=1)
    assert result.exit_time == START + timedelta(minutes=2)


def test_default_five_bar_horizon_requires_all_five_bars():
    engine = evaluator(5)
    start(engine)
    for index in range(1, 5):
        assert engine.advance(bar(index)) == ()
    result, = engine.advance(bar(5))
    assert result.entry_time == START + timedelta(minutes=1)
    assert result.exit_time == START + timedelta(minutes=6)
    assert result.holding_period_bars == 5


def test_calendar_month_horizon_follows_month_boundaries_not_fixed_day_counts():
    def monthly(month, next_month):
        start, end = START.replace(month=month), START.replace(month=next_month)
        return bar(month, interval="1M", open_time=start, close_time=end, event_time=end, received_at=end)
    engine = BacktestEvaluator(symbols=("BTCUSDT",), interval="1M", settings=BacktestSettings(holding_period_bars=2))
    start(engine, monthly(1, 2))
    assert engine.advance(monthly(2, 3)) == ()
    result, = engine.advance(monthly(3, 4))
    assert result.entry_time == START.replace(month=2)
    assert result.exit_time == START.replace(month=4)


@pytest.mark.parametrize("direction,favorable,adverse", [("LONG", ".25", "-.2"), ("SHORT", ".2", "-.25")])
def test_excursions_use_only_entry_through_exit_bars(direction, favorable, adverse):
    engine = evaluator()
    start(engine, bar(high=1000, low=1), direction=direction)
    engine.advance(bar(1, opened="100", closed="110", high=120, low=80))
    result, = engine.advance(bar(2, opened="110", closed="115", high=125, low=90))
    assert result.favorable_excursion == Decimal(favorable)
    assert result.adverse_excursion == Decimal(adverse)
    assert engine.advance(bar(3, high=1000, low=1)) == ()


def test_flat_signal_has_zero_excursions_but_positive_cost():
    engine = evaluator(1)
    start(engine)
    result, = engine.advance(bar(1, opened="100", closed="100", high=100, low=100))
    assert result.favorable_excursion == result.adverse_excursion == 0
    assert result.returns.gross_return == 0 and result.returns.net_return == Decimal("-.0014")


def test_end_without_next_bar_is_incomplete_not_a_same_close_entry():
    engine = evaluator()
    start(engine)
    result, = engine.finish()
    assert result.status == "INCOMPLETE" and result.reason == "missing_entry_bar"
    assert result.entry_time is result.entry_price_raw is result.exit_time is result.returns is None
    assert engine.finish() == ()


def test_end_after_entry_keeps_entry_but_never_invents_exit_or_costs():
    engine = evaluator(5)
    start(engine)
    engine.advance(bar(1, opened="123"))
    result, = engine.finish()
    assert result.reason == "dataset_ended" and result.entry_price_raw == 123
    assert result.entry_time == START + timedelta(minutes=1)
    assert result.exit_time is result.exit_price_raw is result.returns is None
    assert result.favorable_excursion is result.adverse_excursion is None


@pytest.mark.parametrize("entered,reason", [(False, "missing_entry_bar"), (True, "missing_horizon_bar")])
def test_missing_intermediate_bar_cannot_shift_horizon_to_later_observations(entered, reason):
    engine = evaluator(3)
    start(engine)
    if entered:
        engine.advance(bar(1))
    result, = engine.advance(bar(3))
    assert result.status == "INCOMPLETE" and result.reason == reason
    assert result.returns is None and engine.pending_count == 0


def test_overlapping_unique_signals_are_evaluated_independently():
    engine = evaluator(2, fee_bps_per_side=0, slippage_bps_per_side=0)
    first = start(engine)
    engine.advance(bar(1, opened="100", closed="105"))
    second = historical_decision(bar(1, opened="100", closed="105"))
    assert engine.accept(second) and engine.pending_count == 2
    result1, = engine.advance(bar(2, opened="120", closed="110"))
    result2, = engine.advance(bar(3, opened="110", closed="120"))
    assert result1.decision_id == first.decision.decision_id and result1.returns.net_return == Decimal(".1")
    assert result2.decision_id == second.decision.decision_id and result2.returns.net_return == 0


def test_duplicate_reads_only_produce_one_outcome():
    engine = evaluator(1)
    observation = start(engine)
    assert not engine.accept(observation) and engine.duplicate_reads == 1
    assert engine.pending_count == 1
    assert len(engine.advance(bar(1))) == 1
    assert engine.finish() == ()


@pytest.mark.parametrize("outcome", ["NO_ACTION", "BLOCKED"])
def test_noneligible_decisions_are_diagnostic_only(outcome):
    engine = evaluator(1)
    start(engine, outcome=outcome)
    assert engine.pending_count == 0
    assert engine.advance(bar(1)) == engine.finish() == ()


def test_outcome_identity_changes_with_evidence_and_cost_settings():
    def run(price="110", fee=5):
        engine = evaluator(1, fee_bps_per_side=fee)
        start(engine)
        return engine.advance(bar(1, opened="100", closed=price))[0]
    first = run()
    assert first.model_dump_json() == run().model_dump_json()
    assert first.outcome_id != run("120").outcome_id
    assert first.outcome_id != run(fee=6).outcome_id


def test_symbols_do_not_share_entry_or_horizon_bars():
    engine = evaluator(1, fee_bps_per_side=0, slippage_bps_per_side=0)
    start(engine)
    engine.advance(bar(0, symbol="ETHUSDT"))
    engine.accept(historical_decision(bar(0, symbol="ETHUSDT"), direction="SHORT"))
    btc, = engine.advance(bar(1, opened="100", closed="110"))
    eth, = engine.advance(bar(1, symbol="ETHUSDT", opened="200", closed="180"))
    assert btc.symbol == "BTCUSDT" and eth.symbol == "ETHUSDT"
    assert btc.entry_price_raw == 100 and eth.entry_price_raw == 200
    assert btc.returns.net_return == eth.returns.net_return == Decimal(".1")


def test_unsafe_decision_copies_and_incorrect_source_bar_fail():
    engine = evaluator()
    engine.advance(bar())
    source = historical_decision(bar())
    for update in ({"direction": "NEUTRAL"}, {"agreement": Decimal("NaN")}, {"generated_at": START}):
        with pytest.raises(ValueError):
            engine.accept(source.model_copy(update={"decision": source.decision.model_copy(update=update)}))
    with pytest.raises(ValueError, match="current finalized bar"):
        engine.accept(historical_decision(bar(1)))
    assert engine.accept(source)
    assert engine.pending_count == 1


@pytest.mark.parametrize("event", [bar(), bar(-1), bar(1, symbol="OTHER"), bar(1).model_copy(update={"high": 0})])
def test_bad_or_out_of_order_bars_fail(event):
    engine = evaluator()
    engine.advance(bar())
    with pytest.raises(ValueError):
        engine.advance(event)


def test_finished_evaluator_cannot_be_reused_silently():
    engine = evaluator()
    engine.finish()
    with pytest.raises(RuntimeError):
        engine.advance(bar())
    with pytest.raises(RuntimeError):
        engine.accept(historical_decision(bar()))
