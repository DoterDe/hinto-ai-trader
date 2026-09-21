"""Canonicalize bounded local evidence; reuse Phase 6 bar and identity contracts."""

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext

from pydantic import TypeAdapter

from src.application.backtest_identity import DatasetIdentity
from src.application.feature_history import next_open_time
from src.application.historical_bars import symbols_for_replay, validate_bar
from src.domain.backtesting import HistoricalInterval
from src.domain.historical_dataset import (
    MAX_INPUT_BARS, MAX_SYMBOLS, SCHEMA_VERSION,
    DatasetCoverage, DatasetGap, DatasetIssue, DatasetValidationResult, HistoricalDataset,
    HistoricalDatasetManifest, SourceLabel, canonical_decimal, require_utc,
)
from src.domain.market_data import KlineEvent
from src.strategies.identity import identity


def _slot(boundary: datetime, interval: str) -> int:
    """Integer grid index, including calendar months; independent of gap length."""
    require_utc(boundary)
    count, unit = int(interval[:-1]), interval[-1]
    if unit == "M":
        if (boundary.day, boundary.hour, boundary.minute, boundary.second, boundary.microsecond) != (1, 0, 0, 0, 0):
            raise ValueError("month boundary must be the first day at UTC midnight")
        value = (boundary.year - 1970) * 12 + boundary.month - 1
        quotient, remainder = divmod(value, count)
    else:
        anchor = datetime(1970, 1, 5 if unit == "w" else 1, tzinfo=timezone.utc)
        width = timedelta(seconds=count * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit])
        quotient, remainder = divmod(boundary - anchor, width)
    if remainder:
        raise ValueError("boundary is not aligned to the historical interval grid")
    return quotient


def _coverage(symbol: str, bars: list[KlineEvent], start: datetime, end: datetime, interval: str) -> DatasetCoverage:
    gaps = []
    cursor = start
    for bar in bars:
        if bar.open_time > cursor:
            gaps.append(DatasetGap(start=cursor, end=bar.open_time,
                                   missing_bars=_slot(bar.open_time, interval) - _slot(cursor, interval)))
        cursor = bar.close_time
    if cursor < end:
        gaps.append(DatasetGap(start=cursor, end=end, missing_bars=_slot(end, interval) - _slot(cursor, interval)))
    expected = _slot(end, interval) - _slot(start, interval)
    with localcontext(Context(prec=34)):
        fraction = Decimal(len(bars)) / Decimal(expected)
    return DatasetCoverage(symbol=symbol, observed_bars=len(bars), expected_bars=expected,
        missing_bars=expected - len(bars), coverage_fraction=fraction,
        first_open=bars[0].open_time if bars else None, last_boundary=bars[-1].close_time if bars else None,
        gaps=tuple(gaps))


def _invalid(code: str, *, symbol: str | None = None, open_time: datetime | None = None) -> DatasetValidationResult:
    return DatasetValidationResult(status="INVALID", issues=(DatasetIssue(code=code, symbol=symbol, open_time=open_time),))


def validate_historical_dataset(bars: Iterable[KlineEvent], *, symbols: Sequence[str], interval: str = "1m",
                                source_label: str = "local-public-bars", start: datetime | None = None,
                                end: datetime | None = None) -> DatasetValidationResult:
    """Return no usable dataset on invalid evidence; diagnose identical duplicates.

    Scope is explicit. Optional [start, end) boundaries must be supplied together;
    otherwise use the observed extent. Bounds never trim rows. At most 100,000
    input rows (including duplicates) are consumed plus one overflow sentinel.
    No paths, clocks, live cache, analytical settings or outcomes enter this layer.
    """
    try:
        if isinstance(symbols, str) or not 0 < len(symbols) <= MAX_SYMBOLS:
            return _invalid("invalid_scope")
        allowed = symbols_for_replay(symbols)
        interval = TypeAdapter(HistoricalInterval).validate_python(interval)
        label = TypeAdapter(SourceLabel).validate_python(source_label)
        next_open_time(datetime(2000, 1, 1, tzinfo=timezone.utc), interval)
    except (ValueError, TypeError, OverflowError):
        return _invalid("invalid_scope")
    try:
        if (start is None) != (end is None):
            raise ValueError("both declared boundaries are required")
        if start is not None:
            if _slot(end, interval) <= _slot(start, interval):
                raise ValueError("end must follow start")
    except (ValueError, TypeError, OverflowError):
        return _invalid("invalid_bounds")
    unique: dict[tuple[datetime, str], KlineEvent] = {}
    duplicates: dict[tuple[datetime, str], int] = {}
    input_count = 0
    try:
        for raw in bars:
            input_count += 1
            if input_count > MAX_INPUT_BARS:
                return _invalid("limit_exceeded")
            if not isinstance(raw, KlineEvent):
                return _invalid("invalid_bar")
            for field in ("open_time", "close_time", "event_time", "received_at"):
                require_utc(getattr(raw, field))
            event = validate_bar(raw)
            try:
                numbers = {field: canonical_decimal(value) for field, value in event.model_dump().items()
                           if isinstance(value, Decimal)}
            except ValueError:
                return _invalid("limit_exceeded")
            event = KlineEvent.model_validate(event.model_copy(update=numbers))
            if event.trade_count.bit_length() > 63:
                return _invalid("limit_exceeded")
            if event.symbol not in allowed or event.interval != interval:
                return _invalid("scope_mismatch")
            if start is not None and not start <= event.open_time < event.close_time <= end:
                return _invalid("invalid_bounds")
            key = (event.open_time, event.symbol)
            if key in unique:
                if unique[key] != event:
                    return _invalid("conflicting_duplicate", symbol=event.symbol, open_time=event.open_time)
                duplicates[key] = duplicates.get(key, 0) + 1
            else:
                unique[key] = event
    except (ValueError, TypeError, OverflowError):
        return _invalid("invalid_bar")
    if not unique:
        return _invalid("empty_dataset")
    ordered = tuple(sorted(unique.values(), key=lambda bar: (bar.event_time, bar.symbol)))
    start = ordered[0].open_time if start is None else start
    end = ordered[-1].close_time if end is None else end
    by_symbol: dict[str, list[KlineEvent]] = {symbol: [] for symbol in allowed}
    content = DatasetIdentity()
    for event in ordered:
        by_symbol[event.symbol].append(event)
        content.add(event)
    coverage = tuple(_coverage(symbol, by_symbol[symbol], start, end, interval) for symbol in allowed)
    issues = tuple(DatasetIssue(code="identical_duplicate", symbol=symbol, open_time=opened, count=count)
                   for (opened, symbol), count in sorted(duplicates.items()))
    missing = sum(item.missing_bars for item in coverage)
    digest = content.value.removeprefix("dataset_")
    dataset_id = identity("historical_dataset", {"schema_version": SCHEMA_VERSION, "symbols": allowed,
        "interval": interval, "start": start, "end": end, "content_checksum": digest})
    manifest = HistoricalDatasetManifest(dataset_id=dataset_id, content_checksum=digest,
        replay_dataset_id=content.value, source_label=label, symbols=allowed, interval=interval,
        start=start, end=end, first_open=ordered[0].open_time, first_boundary=ordered[0].event_time,
        last_boundary=ordered[-1].event_time, input_bar_count=input_count, total_bars=len(ordered),
        duplicate_count=sum(duplicates.values()), gap_count=sum(len(item.gaps) for item in coverage),
        missing_bar_count=missing, status="VALID_WITH_GAPS" if missing else "VALID", coverage=coverage, duplicates=issues)
    return DatasetValidationResult(status=manifest.status,
        dataset=HistoricalDataset(manifest=manifest, bars=ordered), issues=issues)


def verify_historical_dataset(dataset: HistoricalDataset) -> HistoricalDataset:
    """Recompute every derived field and hash, including on model_copy inputs."""
    dataset = HistoricalDataset.model_validate(dataset)
    manifest = dataset.manifest
    by_key = {(bar.open_time, bar.symbol): bar for bar in dataset.bars}

    def source_rows() -> Iterable[KlineEvent]:
        yield from dataset.bars
        seen = set()
        for issue in manifest.duplicates:
            key = (issue.open_time, issue.symbol)
            if key in seen or key not in by_key:
                raise ValueError("invalid duplicate provenance")
            seen.add(key)
            for _ in range(issue.count):
                yield by_key[key]

    rebuilt = validate_historical_dataset(source_rows(), symbols=manifest.symbols, interval=manifest.interval,
        source_label=manifest.source_label, start=manifest.start, end=manifest.end).require_dataset()
    if rebuilt != dataset:
        raise ValueError("dataset manifest, canonical rows or identity do not reconcile")
    return rebuilt
