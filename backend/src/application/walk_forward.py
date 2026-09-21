"""Deterministic interval-boundary splits over canonical Batch 1 evidence."""

from bisect import bisect_left
from datetime import datetime

from src.application.feature_history import next_open_time
from src.application.feature_settings import FeatureSettings
from src.application.historical_dataset import _coverage, _slot, verify_historical_dataset
from src.domain.historical_dataset import HistoricalDataset
from src.domain.market_data import KlineEvent
from src.domain.walk_forward import (
    MAX_REPLAY_ROWS, MAX_SPLITS, MAX_TEST_ROWS, WalkForwardMode, WalkForwardPlan,
    WalkForwardProtocol, WalkForwardSplit,
)
from src.strategies.identity import identity


def required_warmup(settings: FeatureSettings) -> int:
    """Sample requirements from FeatureSettings/FeatureEngine, not indicator math.

    Excludes trade/book/mark groups: a candle replay cannot warm absent streams.
    Tests reconcile this maximum against the actual engine's public status.
    """
    config = FeatureSettings.model_validate(settings.model_dump())
    return max(config.ema_long, config.rsi_period + 1, config.roc_period + 1,
               config.atr_period, config.volatility_window + 1, config.vwap_window,
               config.relative_volume_window + 1, config.rolling_return_windows[-1] + 1)


def protocol_identity(protocol: WalkForwardProtocol) -> str:
    protocol = WalkForwardProtocol.model_validate(protocol)
    return identity("walk_protocol", protocol.model_dump(exclude={"dataset_id"}))


def boundary_at(start: datetime, interval: str, index: int) -> datetime:
    return start if index == 0 else next_open_time(start, f"{int(interval[:-1]) * index}{interval[-1]}")


def _trailing_count(bars: list[KlineEvent], boundary: datetime) -> int:
    count = 0
    for bar in reversed(bars):
        if bar.close_time != boundary:
            break
        count += 1
        boundary = bar.open_time
    return count


def build_walk_forward_plan(dataset: HistoricalDataset, protocol: WalkForwardProtocol,
                            *, feature_settings: FeatureSettings | None = None) -> WalkForwardPlan:
    dataset = verify_historical_dataset(dataset)
    return _build_plan(dataset, protocol, feature_settings if feature_settings is not None else FeatureSettings())


def _build_plan(dataset: HistoricalDataset, protocol: WalkForwardProtocol, settings: FeatureSettings) -> WalkForwardPlan:
    """Caller supplies a verified dataset. Missing slots remain missing evidence."""
    protocol = WalkForwardProtocol.model_validate(protocol)
    manifest = dataset.manifest
    if (protocol.dataset_id != manifest.dataset_id or protocol.dataset_schema_version != manifest.schema_version
            or protocol.symbols != manifest.symbols or protocol.interval != manifest.interval):
        raise ValueError("walk-forward protocol must match the dataset identity and scope")
    actual_warmup = required_warmup(settings)
    if protocol.warmup_boundaries < actual_warmup:
        raise ValueError(f"protocol warmup must cover the feature requirement of {actual_warmup} bars")
    first_test = (protocol.rolling_context_boundaries if protocol.mode == WalkForwardMode.ROLLING
                  else protocol.minimum_context_boundaries)
    total = _slot(manifest.end, manifest.interval) - _slot(manifest.start, manifest.interval)
    count = max(0, (total - first_test + protocol.step_boundaries - 1) // protocol.step_boundaries)
    if count > MAX_SPLITS:
        raise ValueError("walk-forward split budget exceeded")
    protocol_id = protocol_identity(protocol)
    opens = [bar.open_time for bar in dataset.bars]
    ranges = []
    replay_rows = test_rows = 0
    for test_index in range(first_test, total, protocol.step_boundaries):
        context_index = 0 if protocol.mode == WalkForwardMode.EXPANDING else test_index - protocol.rolling_context_boundaries
        stop = min(total, test_index + protocol.test_boundaries)
        left, middle, right = (boundary_at(manifest.start, protocol.interval, index) for index in (context_index, test_index, stop))
        lo, mid, hi = (bisect_left(opens, time) for time in (left, middle, right))
        replay_rows += hi - lo
        test_rows += hi - mid
        if replay_rows > MAX_REPLAY_ROWS or test_rows > MAX_TEST_ROWS:
            raise ValueError("walk-forward replay/evidence budget exceeded")
        ranges.append((context_index, test_index, stop, left, middle, right, lo, mid, hi))
    splits = []
    for ordinal, (context_index, test_index, stop, left, middle, right, lo, mid, hi) in enumerate(ranges):
        context, test = dataset.bars[lo:mid], dataset.bars[mid:hi]
        context_by_symbol = {symbol: [] for symbol in protocol.symbols}
        test_by_symbol = {symbol: [] for symbol in protocol.symbols}
        for bar in context:
            context_by_symbol[bar.symbol].append(bar)
        for bar in test:
            test_by_symbol[bar.symbol].append(bar)
        context_coverage = tuple(_coverage(symbol, context_by_symbol[symbol], left, middle, protocol.interval)
                                 for symbol in protocol.symbols)
        test_coverage = tuple(_coverage(symbol, test_by_symbol[symbol], middle, right, protocol.interval)
                              for symbol in protocol.symbols)
        insufficient = tuple(symbol for symbol in protocol.symbols
                             if _trailing_count(context_by_symbol[symbol], middle) < protocol.warmup_boundaries)
        warnings = []
        if any(item.missing_bars for item in (*context_coverage, *test_coverage)):
            warnings.append("VALID_WITH_GAPS")
        partial = stop - test_index < protocol.test_boundaries
        if partial:
            warnings.append("PARTIAL_TEST_WINDOW")
        if not test:
            warnings.append("NO_TEST_OBSERVATIONS")
        if protocol.allow_test_overlap:
            warnings.append("OVERLAPPING_TEST_WINDOWS")
        if protocol.step_boundaries > protocol.test_boundaries:
            warnings.append("SKIPPED_TEST_BOUNDARIES")
        status = ("INSUFFICIENT_CONTEXT" if insufficient else "PARTIAL_WINDOW_REJECTED"
                  if partial and protocol.partial_window == "REJECT" else "READY")
        structure = dict(protocol_id=protocol_id, ordinal=ordinal, context_start=left, context_end=middle,
                         test_start=middle, test_end=right)
        splits.append(WalkForwardSplit(split_id=identity("walk_split", structure), dataset_id=manifest.dataset_id,
            **structure, context_boundary_count=test_index - context_index, test_boundary_count=stop - test_index,
            observed_context_boundaries=len({bar.event_time for bar in context}),
            observed_test_boundaries=len({bar.event_time for bar in test}), required_warmup=protocol.warmup_boundaries,
            context_coverage=context_coverage, test_coverage=test_coverage,
            insufficient_context_symbols=insufficient, status=status, warnings=tuple(warnings)))
    return WalkForwardPlan(dataset_id=manifest.dataset_id, protocol_id=protocol_id,
        required_warmup=protocol.warmup_boundaries, total_boundary_count=total,
        observed_boundary_count=len({bar.event_time for bar in dataset.bars}), splits=tuple(splits),
        status="READY" if splits else "INSUFFICIENT_CONTEXT" if total < first_test else "NO_TEST_BOUNDARIES")
