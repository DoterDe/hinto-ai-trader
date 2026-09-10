from datetime import timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backtest_fixtures import START, bar
from src.application.backtest_identity import DatasetIdentity, outcome_identity, settings_identity
from src.application.backtest_settings import BacktestSettings
from src.application.historical_bars import ordered_bars, validate_bar
from src.domain.backtesting import BacktestSignalOutcome


def incomplete(**updates):
    return BacktestSignalOutcome(**(dict(outcome_id="outcome_test", decision_id="decision_test",
        observation_id="observation_test", symbol="BTCUSDT", interval="1m", direction="LONG",
        decision_time=START + timedelta(minutes=1), source_bar_open_time=START,
        holding_period_bars=5, backtest_settings_id="settings_test", status="INCOMPLETE",
        reason="dataset_ended") | updates))


def test_exact_defaults_and_immutable_outcome_and_settings():
    settings = BacktestSettings()
    assert settings.model_dump() == dict(holding_period_bars=5, fee_bps_per_side=Decimal(5),
        slippage_bps_per_side=Decimal(2), chronological_segments=4)
    result = incomplete()
    assert BacktestSignalOutcome.model_validate_json(result.model_dump_json()) == result
    for value, field in ((settings, "holding_period_bars"), (result, "outcome_id"), (bar(), "close")):
        with pytest.raises(ValidationError):
            setattr(value, field, 2)


@pytest.mark.parametrize("field", ["quantity", "leverage", "balance", "account", "order_id", "api_key", "execution_mode"])
def test_outcomes_have_no_executable_or_account_fields(field):
    assert field not in BacktestSignalOutcome.model_fields
    with pytest.raises(ValidationError):
        incomplete(**{field: 1})


@pytest.mark.parametrize("field,value", [
    ("holding_period_bars", 0), ("holding_period_bars", -1), ("holding_period_bars", True),
    ("holding_period_bars", 1.5), ("holding_period_bars", "2.0"),
    ("fee_bps_per_side", -1), ("fee_bps_per_side", "NaN"), ("fee_bps_per_side", "Infinity"),
    ("fee_bps_per_side", True), ("slippage_bps_per_side", -1), ("slippage_bps_per_side", 10000),
    ("slippage_bps_per_side", "NaN"), ("slippage_bps_per_side", "Infinity"), ("slippage_bps_per_side", True),
    ("chronological_segments", 0), ("chronological_segments", 101), ("chronological_segments", True),
    ("chronological_segments", 1.5), ("optimizer", True),
])
def test_invalid_settings_fail(field, value):
    with pytest.raises(ValidationError):
        BacktestSettings(**{field: value})


def test_environment_settings_and_validation_bypassing_copy(monkeypatch):
    monkeypatch.setenv("BACKTEST_HOLDING_PERIOD_BARS", "7")
    monkeypatch.setenv("BACKTEST_FEE_BPS_PER_SIDE", "6.5")
    monkeypatch.setenv("BACKTEST_CHRONOLOGICAL_SEGMENTS", "2")
    settings = BacktestSettings()
    assert settings.holding_period_bars == 7 and settings.fee_bps_per_side == Decimal("6.5")
    assert settings.chronological_segments == 2
    with pytest.raises(ValidationError):
        BacktestSettings.model_validate(settings.model_copy(update={"holding_period_bars": True}))


@pytest.mark.parametrize("updates", [
    {"status": "COMPLETED"}, {"direction": "NEUTRAL"}, {"direction": "BUY"},
    {"decision_time": START}, {"decision_time": START.replace(tzinfo=None)},
    {"exit_price_raw": 101}, {"exit_time": START + timedelta(minutes=6)},
    {"entry_time": START}, {"entry_price_raw": 100}, {"holding_period_bars": True},
    {"reason": "horizon_completed"},
    {"interval": "0m"}, {"interval": ""},
])
def test_incoherent_outcome_is_rejected(updates):
    with pytest.raises(ValidationError):
        incomplete(**updates)


def test_normalized_bar_reuses_existing_contract_and_canonicalizes_time():
    event = bar()
    assert validate_bar(event) == event
    inclusive = event.model_copy(update={"close_time": event.close_time - timedelta(milliseconds=1)})
    assert validate_bar(inclusive) == event
    offset = timezone(timedelta(hours=5))
    shifted = event.model_copy(update={name: getattr(event, name).astimezone(offset)
        for name in ("open_time", "close_time", "event_time", "received_at")})
    assert validate_bar(shifted).model_dump_json() == event.model_dump_json()


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, "-1"])
def test_historical_numbers_are_revalidated(field, value):
    with pytest.raises(ValueError):
        validate_bar(bar().model_copy(update={field: value}))


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_zero_prices_are_rejected(field):
    with pytest.raises(ValueError):
        validate_bar(bar().model_copy(update={field: 0}))


@pytest.mark.parametrize("updates", [
    {"low": Decimal(102)}, {"high": Decimal(99)}, {"open": Decimal(102)}, {"close": Decimal(99)},
    {"taker_buy_volume": Decimal(11)}, {"taker_buy_quote_volume": Decimal(2000)},
    {"volume": Decimal(0), "taker_buy_volume": Decimal(0)}, {"is_closed": False},
    {"open_time": START + timedelta(seconds=1)}, {"close_time": START},
    {"close_time": START + timedelta(seconds=30)}, {"event_time": START + timedelta(seconds=59)},
    {"received_at": START + timedelta(seconds=61)}, {"trade_count": True},
])
def test_incoherent_historical_copies_fail(updates):
    with pytest.raises(ValueError):
        validate_bar(bar().model_copy(update=updates))


@pytest.mark.parametrize("field", ["open_time", "close_time", "event_time", "received_at"])
@pytest.mark.parametrize("value", [START.replace(tzinfo=None), 1577836800])
def test_raw_numeric_or_naive_historical_times_fail(field, value):
    with pytest.raises(ValueError):
        validate_bar(bar().model_copy(update={field: value}))


def test_zero_volume_is_valid_but_no_volume_is_invented():
    result = validate_bar(bar(volume=0, quote_volume=0, taker_buy_volume=0, taker_buy_quote_volume=0))
    assert result.volume == result.quote_volume == 0


def test_equal_timestamp_symbols_are_sorted_and_gaps_are_preserved():
    bars = [bar(0, symbol="ETHUSDT"), bar(0), bar(4)]
    result = list(ordered_bars(iter(bars), symbols=("ETHUSDT", "BTCUSDT"), interval="1m"))
    assert [(event.open_time, event.symbol) for event in result] == [
        (START, "BTCUSDT"), (START, "ETHUSDT"), (START + timedelta(minutes=4), "BTCUSDT")]
    assert len(result) == 3


@pytest.mark.parametrize("bars", [[bar(), bar()], [bar(1), bar()], [bar(symbol="OTHER")], [bar(interval="2m")]])
def test_duplicates_unsorted_and_wrong_scope_fail(bars):
    with pytest.raises(ValueError):
        list(ordered_bars(bars, symbols=("BTCUSDT",), interval="1m"))


def test_calendar_month_bars_use_true_month_end():
    end = START.replace(month=2)
    event = bar(interval="1M", close_time=end, event_time=end, received_at=end)
    assert validate_bar(event).close_time == end
    with pytest.raises(ValueError):
        validate_bar(event.model_copy(update={"open_time": START + timedelta(days=1)}))


def test_dataset_and_settings_identities_are_stable_and_sensitive():
    first, second, changed = DatasetIdentity(), DatasetIdentity(), DatasetIdentity()
    first.add(bar())
    second.add(bar(opened="100.000", closed="101.00"))
    changed.add(bar(closed="102"))
    assert first.count == 1 and first.value == second.value != changed.value
    settings = settings_identity(BacktestSettings())
    assert settings == settings_identity(BacktestSettings(fee_bps_per_side="5.00"))
    assert settings != settings_identity(BacktestSettings(fee_bps_per_side=6))
    args = ("decision_test", settings, START, first.value, "COMPLETED", "horizon_completed")
    assert outcome_identity(*args) == outcome_identity(*args)
    assert outcome_identity(*args) != outcome_identity(*(args[:3] + (changed.value,) + args[4:]))
