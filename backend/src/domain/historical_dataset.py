"""Bounded, exchange-independent historical research evidence contracts."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints, model_validator

from src.domain.backtesting import BacktestModel, Count, HistoricalInterval, PositiveCount
from src.domain.market_data import KlineEvent, MarketSymbol

SCHEMA_VERSION = "historical-dataset-v1"
MAX_INPUT_BARS = 100_000
MAX_SYMBOLS = 128
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_DECIMAL_DIGITS = 128
MAX_DECIMAL_EXPONENT = 1_000


def canonical_decimal(value: Decimal) -> Decimal:
    """Exact, context-independent value; insignificant scale is not evidence."""
    if not value.is_finite():
        raise ValueError("nonfinite dataset decimal")
    sign, digits, exponent = value.as_tuple()
    length = len(digits)
    while length and digits[length - 1] == 0:
        length -= 1
    if not length:
        return Decimal(0)
    exponent += len(digits) - length
    if length > MAX_DECIMAL_DIGITS or abs(exponent) > MAX_DECIMAL_EXPONENT:
        raise ValueError("dataset decimal exceeds canonical numeric limits")
    return Decimal((sign, digits[:length], exponent))


def require_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("dataset timestamps must be aware UTC")
    return value


UtcTime = Annotated[AwareDatetime, AfterValidator(require_utc)]
SourceLabel = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
Checksum = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DatasetId = Annotated[str, StringConstraints(pattern=r"^historical_dataset_[0-9a-f]{64}$")]
DatasetStatus = Literal["VALID", "VALID_WITH_GAPS", "INVALID"]


class DatasetIssue(BacktestModel):
    code: Literal["invalid_scope", "invalid_bounds", "invalid_bar", "scope_mismatch",
                  "empty_dataset", "limit_exceeded", "identical_duplicate", "conflicting_duplicate"]
    symbol: MarketSymbol | None = None
    open_time: UtcTime | None = None
    count: PositiveCount = 1


class DatasetGap(BacktestModel):
    """Missing open-time slots in [start, end); no materialized missing bars."""

    start: UtcTime
    end: UtcTime
    missing_bars: PositiveCount


class DatasetCoverage(BacktestModel):
    symbol: MarketSymbol
    observed_bars: Count
    expected_bars: PositiveCount
    missing_bars: Count
    coverage_fraction: Annotated[Decimal, Field(ge=0, le=1)]
    first_open: UtcTime | None
    last_boundary: UtcTime | None
    gaps: tuple[DatasetGap, ...] = Field(max_length=MAX_INPUT_BARS + 1)

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if self.observed_bars + self.missing_bars != self.expected_bars:
            raise ValueError("coverage counts do not reconcile")
        if sum(gap.missing_bars for gap in self.gaps) != self.missing_bars:
            raise ValueError("gap counts do not reconcile")
        return self


class HistoricalDatasetManifest(BacktestModel):
    schema_version: Literal["historical-dataset-v1"] = SCHEMA_VERSION
    dataset_id: DatasetId
    content_checksum: Checksum
    replay_dataset_id: Annotated[str, StringConstraints(pattern=r"^dataset_[0-9a-f]{64}$")]
    source_label: SourceLabel
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1, max_length=MAX_SYMBOLS)
    interval: HistoricalInterval
    start: UtcTime
    end: UtcTime
    first_open: UtcTime
    first_boundary: UtcTime
    last_boundary: UtcTime
    input_bar_count: Annotated[int, Field(strict=True, gt=0, le=MAX_INPUT_BARS)]
    total_bars: Annotated[int, Field(strict=True, gt=0, le=MAX_INPUT_BARS)]
    duplicate_count: Count
    conflict_count: Literal[0] = 0
    gap_count: Count
    missing_bar_count: Count
    status: Literal["VALID", "VALID_WITH_GAPS"]
    coverage: tuple[DatasetCoverage, ...] = Field(min_length=1, max_length=MAX_SYMBOLS)
    duplicates: tuple[DatasetIssue, ...] = Field(max_length=MAX_INPUT_BARS)

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if self.symbols != tuple(sorted(set(self.symbols))):
            raise ValueError("dataset symbols must be unique and sorted")
        if tuple(item.symbol for item in self.coverage) != self.symbols:
            raise ValueError("coverage must match declared symbols")
        if not self.start <= self.first_open < self.first_boundary <= self.last_boundary <= self.end:
            raise ValueError("dataset boundaries do not reconcile")
        if self.input_bar_count != self.total_bars + self.duplicate_count:
            raise ValueError("input and duplicate counts do not reconcile")
        if (sum(item.observed_bars for item in self.coverage) != self.total_bars
                or sum(item.missing_bars for item in self.coverage) != self.missing_bar_count
                or sum(len(item.gaps) for item in self.coverage) != self.gap_count):
            raise ValueError("manifest coverage counts do not reconcile")
        if self.status != ("VALID_WITH_GAPS" if self.missing_bar_count else "VALID"):
            raise ValueError("manifest status must disclose gaps")
        if (any(item.code != "identical_duplicate" or item.symbol is None or item.open_time is None
                for item in self.duplicates) or sum(item.count for item in self.duplicates) != self.duplicate_count):
            raise ValueError("duplicate diagnostics do not reconcile")
        return self


class HistoricalDataset(BacktestModel):
    manifest: HistoricalDatasetManifest
    bars: tuple[KlineEvent, ...] = Field(min_length=1, max_length=MAX_INPUT_BARS)

    @model_validator(mode="after")
    def canonical_rows(self) -> Self:
        if len(self.bars) != self.manifest.total_bars:
            raise ValueError("canonical row count mismatch")
        previous = None
        for bar in self.bars:
            for field in ("open_time", "close_time", "event_time", "received_at"):
                require_utc(getattr(bar, field))
            key = (bar.event_time, bar.symbol)
            if previous is not None and key <= previous:
                raise ValueError("canonical rows must be ordered and unique")
            previous = key
            if (bar.symbol not in self.manifest.symbols or bar.interval != self.manifest.interval
                    or not bar.is_closed or not self.manifest.start <= bar.open_time < bar.close_time <= self.manifest.end):
                raise ValueError("canonical row outside dataset contract")
        return self


class DatasetValidationResult(BacktestModel):
    status: DatasetStatus
    dataset: HistoricalDataset | None = None
    issues: tuple[DatasetIssue, ...] = Field(max_length=MAX_INPUT_BARS)

    @model_validator(mode="after")
    def status_matches_evidence(self) -> Self:
        if self.status == "INVALID":
            if self.dataset is not None or not self.issues:
                raise ValueError("invalid evidence cannot expose a usable dataset")
        elif self.dataset is None or self.dataset.manifest.status != self.status:
            raise ValueError("valid result requires matching dataset")
        return self

    def require_dataset(self) -> HistoricalDataset:
        if self.dataset is None:
            raise ValueError("invalid historical dataset: " + ", ".join(item.code for item in self.issues))
        return self.dataset
