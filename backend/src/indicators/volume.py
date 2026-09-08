"""Bounded closed-candle volume context from normalized base/quote volumes."""

from collections.abc import Sequence
from decimal import Decimal

from src.domain.market_data import KlineEvent
from src.indicators._numeric import safe_decimal, valid_period


def _valid_volume(candle: KlineEvent) -> bool:
    values = (
        candle.volume, candle.quote_volume, candle.taker_buy_volume,
        candle.taker_buy_quote_volume,
    )
    return (
        candle.is_closed
        and all(isinstance(value, Decimal) and value.is_finite() and value >= 0
                for value in values)
        and candle.taker_buy_volume <= candle.volume
        and candle.taker_buy_quote_volume <= candle.quote_volume
        and (candle.volume != 0 or candle.quote_volume == 0)
    )


@safe_decimal
def rolling_vwap(candles: Sequence[KlineEvent], window: int) -> Decimal | None:
    """Sum quote volume / sum base volume over exactly the last N candles."""
    if not valid_period(window) or len(candles) < window:
        return None
    selected = candles[-window:]
    if not all(_valid_volume(candle) for candle in selected):
        return None
    base = sum((candle.volume for candle in selected), Decimal(0))
    if base == 0:
        return None
    quote = sum((candle.quote_volume for candle in selected), Decimal(0))
    return quote / base


@safe_decimal
def relative_volume(candles: Sequence[KlineEvent], window: int) -> Decimal | None:
    """Latest base volume / mean base volume of the preceding N candles."""
    if not valid_period(window) or len(candles) < window + 1:
        return None
    selected = candles[-(window + 1):]
    if not all(_valid_volume(candle) for candle in selected):
        return None
    preceding = sum((candle.volume for candle in selected[:-1]), Decimal(0))
    if preceding == 0:
        return None
    return selected[-1].volume * window / preceding


@safe_decimal
def taker_buy_ratio(candle: KlineEvent) -> Decimal | None:
    """Share of this candle's base volume attributed to taker buys."""
    if not _valid_volume(candle) or candle.volume == 0:
        return None
    return candle.taker_buy_volume / candle.volume


@safe_decimal
def taker_volume_delta_proxy(candle: KlineEvent) -> Decimal | None:
    """2*taker-buy base volume - total base volume for this candle only.

    This is a signed volume proxy within the normalized candle, not exchange-
    wide order flow or a reconstructed order book.
    """
    if not _valid_volume(candle):
        return None
    return 2 * candle.taker_buy_volume - candle.volume
