"""Immutable numerical observations for future strategies, never trading decisions."""

from decimal import Decimal
from enum import Enum
from typing import Generic, Self, TypeVar

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from src.domain.market_data import MarketSymbol
from src.domain.models import DomainModel


class FeatureModel(DomainModel):
    model_config = ConfigDict(extra="forbid")


class Readiness(str, Enum):
    READY = "ready"
    WARMING_UP = "warming_up"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class GroupStatus(FeatureModel):
    state: Readiness
    reasons: tuple[str, ...] = ()
    required_samples: int = Field(default=1, ge=1)
    available_samples: int = Field(default=0, ge=0)


V = TypeVar("V", bound=FeatureModel)


class FeatureGroup(GroupStatus, Generic[V]):
    values: V | None = None

    @model_validator(mode="after")
    def coherent_availability(self) -> Self:
        if self.state == Readiness.PARTIAL:
            raise ValueError("partial describes a snapshot, not an individual group")
        if (self.state == Readiness.READY) != (self.values is not None):
            raise ValueError("only ready groups carry values")
        if self.state != Readiness.READY and not self.reasons:
            raise ValueError("unavailable groups require a reason")
        return self


class WindowReturn(FeatureModel):
    window: int = Field(gt=0)
    value: Decimal


class TradeFeatures(FeatureModel):
    price: Decimal
    quantity: Decimal


class ReturnFeatures(FeatureModel):
    close: Decimal
    simple_return: Decimal
    log_return: float
    rolling_returns: tuple[WindowReturn, ...]


class TrendFeatures(FeatureModel):
    ema_fast: Decimal
    ema_slow: Decimal
    ema_long: Decimal
    fast_slow_spread: Decimal
    slow_long_spread: Decimal
    distance_from_fast: Decimal
    distance_from_slow: Decimal
    distance_from_long: Decimal


class MomentumFeatures(FeatureModel):
    rsi: Decimal
    roc_percent: Decimal
    close_change: Decimal


class VolatilityFeatures(FeatureModel):
    true_range: Decimal
    atr: Decimal
    normalized_atr: Decimal
    atr_percent: Decimal
    realized_volatility: float


class VolumeFeatures(FeatureModel):
    rolling_vwap: Decimal
    relative_volume: Decimal
    taker_buy_ratio: Decimal
    taker_base_volume_delta_proxy: Decimal


class MicrostructureFeatures(FeatureModel):
    bid: Decimal
    ask: Decimal
    midpoint: Decimal
    spread: Decimal
    spread_bps: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal
    top_of_book_imbalance: Decimal


class MarkFundingFeatures(FeatureModel):
    mark_price: Decimal
    index_price: Decimal
    basis: Decimal
    basis_percent: Decimal
    basis_bps: Decimal
    funding_rate: Decimal
    next_funding_time: AwareDatetime
    seconds_until_funding: float


class RegimeFeatures(FeatureModel):
    normalized_atr: Decimal
    normalized_ema_separation: Decimal
    directional_efficiency: Decimal
    relative_volume: Decimal


class FeatureSource(FeatureModel):
    stream: str
    event_time: AwareDatetime | None = None
    received_at: AwareDatetime | None = None
    stale: bool
    reason: str | None = None
    connection_id: str | None = None
    generation: int | None = None


class FeatureSnapshot(FeatureModel):
    symbol: MarketSymbol
    generated_at: AwareDatetime
    interval: str
    state: Readiness
    reasons: tuple[str, ...]
    sources: tuple[FeatureSource, ...]
    closed_candle_time: AwareDatetime | None
    closed_candles: int = Field(ge=0)
    history_resets: int = Field(ge=0)
    last_history_reset: str | None
    trade: FeatureGroup[TradeFeatures]
    returns: FeatureGroup[ReturnFeatures]
    trend: FeatureGroup[TrendFeatures]
    momentum: FeatureGroup[MomentumFeatures]
    volatility: FeatureGroup[VolatilityFeatures]
    volume: FeatureGroup[VolumeFeatures]
    microstructure: FeatureGroup[MicrostructureFeatures]
    mark_funding: FeatureGroup[MarkFundingFeatures]
    regime: FeatureGroup[RegimeFeatures]


class NamedGroupStatus(GroupStatus):
    name: str


class FeatureSymbolStatus(FeatureModel):
    symbol: MarketSymbol
    state: Readiness
    groups: tuple[NamedGroupStatus, ...]
    closed_candles: int
    history_resets: int
    last_history_reset: str | None


class FeatureEngineStatus(FeatureModel):
    generated_at: AwareDatetime
    running: bool
    interval: str
    history_limit: int
    symbols: tuple[FeatureSymbolStatus, ...]
