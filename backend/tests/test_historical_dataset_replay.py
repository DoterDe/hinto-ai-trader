"""Dataset adapter regressions through the unchanged Phase 6 analytical path."""

from datetime import timedelta

import pytest

from backtest_fixtures import bar, wave_bars
from src.application.backtest_engine import BacktestEngine
from src.application.historical_dataset import validate_historical_dataset
from src.application.historical_dataset_codec import HistoricalDatasetCodec
from src.application.historical_replay import HistoricalReplay


def dataset(rows, symbols=("BTCUSDT",)):
    return validate_historical_dataset(rows, symbols=symbols).require_dataset()


@pytest.mark.asyncio
async def test_canonical_import_preserves_entire_phase6_report_and_ids():
    rows = list(wave_bars())
    canonical = dataset(list(reversed(rows)) + [rows[0]])
    imported = HistoricalDatasetCodec.decode(HistoricalDatasetCodec.encode(canonical))
    engine = BacktestEngine(symbols=imported.manifest.symbols, interval=imported.manifest.interval)
    direct = await engine.run(rows)
    before, after = await engine.run(canonical.bars), await engine.run(imported.bars)
    assert before.model_dump_json() == after.model_dump_json()
    # Phase 6 preserves incidental Decimal scale in raw report JSON. Canonical
    # inputs normalize that scale; every value and content identity is unchanged.
    assert direct == before == after
    assert direct.metadata.run_id == after.metadata.run_id
    assert after.metadata.dataset_id == imported.manifest.replay_dataset_id
    assert after.metrics.completed_count > 0
    for outcome in after.outcomes:
        if outcome.status == "COMPLETED":
            observation = next(item for item in after.decisions if item.decision.decision_id == outcome.decision_id)
            assert outcome.entry_time == observation.source_bar_close_time
            assert outcome.exit_time == outcome.entry_time + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_canonical_full_dataset_does_not_publish_future_bars_to_earlier_frames():
    rows = list(wave_bars())
    changed = rows[:60] + [bar(60, opened="900", closed="901")] + rows[61:]
    original, modified = dataset(rows), dataset(reversed(changed))
    assert original.manifest.dataset_id != modified.manifest.dataset_id
    first = [frame async for frame in HistoricalReplay(symbols=("BTCUSDT",)).frames(original.bars)]
    second = [frame async for frame in HistoricalReplay(symbols=("BTCUSDT",)).frames(modified.bars)]
    assert first[:60] == second[:60]
    assert first[60].features != second[60].features


@pytest.mark.asyncio
async def test_canonical_gap_is_not_filled_and_preserves_incomplete_outcomes():
    rows = list(wave_bars())
    engine = BacktestEngine(symbols=("BTCUSDT",))
    full = await engine.run(rows)
    first_eligible = next(item for item in full.decisions if item.decision.outcome == "ELIGIBLE")
    missing_open = first_eligible.source_bar_close_time
    rows = [row for row in rows if row.open_time != missing_open]
    canonical = dataset(reversed(rows))
    assert canonical.manifest.missing_bar_count == 1
    direct, imported = await engine.run(rows), await engine.run(canonical.bars)
    assert direct == imported
    result = next(item for item in imported.outcomes if item.decision_id == first_eligible.decision.decision_id)
    assert result.reason == "missing_entry_bar"
    assert result.returns is None
    assert imported.metadata.input_count == 79


@pytest.mark.asyncio
async def test_equal_time_multi_symbol_canonicalization_preserves_replay():
    rows = [row for i in range(4) for row in (bar(i, symbol="ETHUSDT"), bar(i))]
    canonical = dataset(reversed(rows), symbols=("ETHUSDT", "BTCUSDT"))
    engine = BacktestEngine(symbols=("ETHUSDT", "BTCUSDT"))
    assert await engine.run(rows) == await engine.run(canonical.bars)
