"""Pure typed value assembly, separate from history and freshness decisions.

Each group is atomic: any undefined or invalid component makes its entire value
object unavailable. In particular, empty book quantities, zero candle volume,
and flat directional-efficiency paths are never replaced with synthetic values.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from pydantic import ValidationError

from src.application.feature_settings import FeatureSettings
from src.domain.features import (
    FeatureModel, MarkFundingFeatures, MicrostructureFeatures, MomentumFeatures,
    RegimeFeatures, ReturnFeatures, TradeFeatures, TrendFeatures,
    VolatilityFeatures, VolumeFeatures, WindowReturn,
)
from src.domain.market_data import (
    BookTickerEvent, KlineEvent, MarkPriceEvent, NormalizedMarketEvent, TradeEvent,
)
from src.indicators._numeric import positive, ratio, safe_decimal
from src.indicators.microstructure import (
    basis, basis_bps, imbalance, midpoint, spread, spread_bps,
)
from src.indicators.momentum import log_return, momentum, roc, rolling_return, rsi, simple_return
from src.indicators.trend import directional_efficiency, ema, ema_spread, price_distance
from src.indicators.volatility import atr, realized_volatility, true_range
from src.indicators.volume import (
    relative_volume, rolling_vwap, taker_buy_ratio, taker_volume_delta_proxy,
)


V = TypeVar("V", bound=FeatureModel)


def _values(model: type[V], **fields: object) -> V | None:
    if any(value is None for value in fields.values()):
        return None
    try:
        return model(**fields)
    except ValidationError:
        return None


@safe_decimal
def calculate_group(
    name: str,
    candles: Sequence[KlineEvent],
    settings: FeatureSettings,
    *,
    event: NormalizedMarketEvent | None = None,
    now: datetime,
) -> FeatureModel | None:
    """Build one ready group's values using a fixed 34-digit Decimal context.

    The caller owns readiness, source freshness and history continuity. Candle
    groups additionally refuse open or future candles. Funding countdown is
    signed: a negative value means the reported funding timestamp has passed.
    No trading action or directional label is produced.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return None

    if name == "trade":
        if not isinstance(event, TradeEvent) or not positive((event.price, event.quantity)):
            return None
        return _values(TradeFeatures, price=event.price, quantity=event.quantity)

    if name == "microstructure":
        if not isinstance(event, BookTickerEvent):
            return None
        return _values(
            MicrostructureFeatures, bid=event.bid_price, ask=event.ask_price,
            midpoint=midpoint(event.bid_price, event.ask_price),
            spread=spread(event.bid_price, event.ask_price),
            spread_bps=spread_bps(event.bid_price, event.ask_price),
            bid_quantity=event.bid_quantity, ask_quantity=event.ask_quantity,
            top_of_book_imbalance=imbalance(event.bid_quantity, event.ask_quantity),
        )

    if name == "mark_funding":
        if (
            not isinstance(event, MarkPriceEvent)
            or not isinstance(event.next_funding_time, datetime)
            or event.next_funding_time.tzinfo is None
            or event.next_funding_time.utcoffset() is None
        ):
            return None
        bps = basis_bps(event.mark_price, event.index_price)
        return _values(
            MarkFundingFeatures, mark_price=event.mark_price, index_price=event.index_price,
            basis=basis(event.mark_price, event.index_price),
            basis_percent=None if bps is None else bps / 100,
            basis_bps=bps, funding_rate=event.funding_rate,
            next_funding_time=event.next_funding_time,
            seconds_until_funding=(event.next_funding_time - now).total_seconds(),
        )

    if not candles or any(
        not isinstance(candle, KlineEvent)
        or candle.is_closed is not True
        or candle.close_time.tzinfo is None
        or candle.close_time.utcoffset() is None
        or candle.close_time > now
        for candle in candles
    ):
        return None
    closes = tuple(candle.close for candle in candles)
    latest = candles[-1]

    if name == "returns":
        if len(closes) < 2:
            return None
        windows = tuple(_values(WindowReturn, window=window, value=rolling_return(closes, window))
                        for window in settings.rolling_return_windows)
        if any(value is None for value in windows):
            return None
        return _values(
            ReturnFeatures, close=latest.close,
            simple_return=simple_return(closes[-1], closes[-2]),
            log_return=log_return(closes[-1], closes[-2]), rolling_returns=windows,
        )

    if name == "trend":
        fast = ema(closes, settings.ema_fast)
        slow = ema(closes, settings.ema_slow)
        long = ema(closes, settings.ema_long)
        return _values(
            TrendFeatures, ema_fast=fast, ema_slow=slow, ema_long=long,
            fast_slow_spread=ema_spread(fast, slow), slow_long_spread=ema_spread(slow, long),
            distance_from_fast=price_distance(latest.close, fast),
            distance_from_slow=price_distance(latest.close, slow),
            distance_from_long=price_distance(latest.close, long),
        )

    if name == "momentum":
        return _values(
            MomentumFeatures, rsi=rsi(closes, settings.rsi_period),
            roc_percent=roc(closes, settings.roc_period), close_change=momentum(closes),
        )

    if name == "volatility":
        average_range = atr(candles, settings.atr_period)
        normalized = None if average_range is None else ratio(average_range, latest.close)
        return _values(
            VolatilityFeatures,
            true_range=true_range(latest.high, latest.low, closes[-2] if len(closes) > 1 else None),
            atr=average_range, normalized_atr=normalized,
            atr_percent=None if normalized is None else normalized * 100,
            realized_volatility=realized_volatility(closes, settings.volatility_window),
        )

    if name == "volume":
        return _values(
            VolumeFeatures, rolling_vwap=rolling_vwap(candles, settings.vwap_window),
            relative_volume=relative_volume(candles, settings.relative_volume_window),
            taker_buy_ratio=taker_buy_ratio(latest),
            taker_base_volume_delta_proxy=taker_volume_delta_proxy(latest),
        )

    if name == "regime":
        average_range = atr(candles, settings.atr_period)
        fast = ema(closes, settings.ema_fast)
        slow = ema(closes, settings.ema_slow)
        separation = ema_spread(fast, slow)
        return _values(
            RegimeFeatures,
            normalized_atr=None if average_range is None else ratio(average_range, latest.close),
            normalized_ema_separation=None if separation is None or slow is None else ratio(separation, slow),
            directional_efficiency=directional_efficiency(closes, settings.roc_period),
            relative_volume=relative_volume(candles, settings.relative_volume_window),
        )
    return None
