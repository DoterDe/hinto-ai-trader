"""Single-observation top-of-book and mark/index numerical context."""

from decimal import Decimal

from src.indicators._numeric import positive, safe_decimal


def _valid_book(bid: Decimal, ask: Decimal) -> bool:
    return positive((bid, ask)) and bid <= ask


@safe_decimal
def midpoint(bid: Decimal, ask: Decimal) -> Decimal | None:
    if not _valid_book(bid, ask):
        return None
    return (bid + ask) / 2


@safe_decimal
def spread(bid: Decimal, ask: Decimal) -> Decimal | None:
    if not _valid_book(bid, ask):
        return None
    return ask - bid


@safe_decimal
def spread_bps(bid: Decimal, ask: Decimal) -> Decimal | None:
    """Absolute spread divided by midpoint, multiplied by 10,000."""
    mid = midpoint(bid, ask)
    if mid is None:
        return None
    return (ask - bid) / mid * 10_000


@safe_decimal
def imbalance(bid_quantity: Decimal, ask_quantity: Decimal) -> Decimal | None:
    """Top-of-book (bid quantity - ask quantity) / combined quantity."""
    if not all(isinstance(value, Decimal) and value.is_finite() and value >= 0
               for value in (bid_quantity, ask_quantity)):
        return None
    denominator = bid_quantity + ask_quantity
    if denominator == 0:
        return None
    return (bid_quantity - ask_quantity) / denominator


@safe_decimal
def basis(mark: Decimal, index: Decimal) -> Decimal | None:
    if not positive((mark, index)):
        return None
    return mark - index


@safe_decimal
def basis_bps(mark: Decimal, index: Decimal) -> Decimal | None:
    """Mark/index basis divided by index price, multiplied by 10,000."""
    difference = basis(mark, index)
    if difference is None:
        return None
    return difference / index * 10_000
