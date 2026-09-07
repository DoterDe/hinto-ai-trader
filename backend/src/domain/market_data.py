"""Exchange-independent market observations and source/sink boundaries.

Depth events are updates only: they are not a reconstructed order book.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from src.domain.models import DomainModel, Identifier


MarketSymbol = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z0-9]{3,32}$")
]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonnegativeDecimal = Annotated[Decimal, Field(ge=0)]
SequenceID = Annotated[int, Field(strict=True, ge=0)]
SafeReason = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class EventType(str, Enum):
    TRADE = "trade"
    KLINE = "kline"
    BOOK_TICKER = "book_ticker"
    MARK_PRICE = "mark_price"
    DEPTH = "depth"


class MarketEvent(DomainModel):
    model_config = ConfigDict(extra="forbid")

    symbol: MarketSymbol
    event_time: AwareDatetime
    received_at: AwareDatetime


class TradeEvent(MarketEvent):
    event_type: Literal[EventType.TRADE] = EventType.TRADE
    aggregate_trade_id: SequenceID
    first_trade_id: SequenceID
    last_trade_id: SequenceID
    price: PositiveDecimal
    quantity: PositiveDecimal
    trade_time: AwareDatetime
    buyer_is_maker: bool = Field(strict=True)
    normal_quantity: NonnegativeDecimal | None = None

    @model_validator(mode="after")
    def ordered_trade_ids(self) -> Self:
        if self.first_trade_id > self.last_trade_id:
            raise ValueError("first_trade_id must not exceed last_trade_id")
        return self


class KlineEvent(MarketEvent):
    event_type: Literal[EventType.KLINE] = EventType.KLINE
    interval: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*[smhdwM]$")]
    open_time: AwareDatetime
    close_time: AwareDatetime
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonnegativeDecimal
    quote_volume: NonnegativeDecimal
    trade_count: SequenceID
    is_closed: bool = Field(strict=True)
    taker_buy_volume: NonnegativeDecimal
    taker_buy_quote_volume: NonnegativeDecimal

    @model_validator(mode="after")
    def ordered_candle_times(self) -> Self:
        if self.open_time > self.close_time:
            raise ValueError("open_time must not exceed close_time")
        return self


class BookTickerEvent(MarketEvent):
    event_type: Literal[EventType.BOOK_TICKER] = EventType.BOOK_TICKER
    update_id: SequenceID
    bid_price: PositiveDecimal
    bid_quantity: NonnegativeDecimal
    ask_price: PositiveDecimal
    ask_quantity: NonnegativeDecimal
    transaction_time: AwareDatetime


class MarkPriceEvent(MarketEvent):
    event_type: Literal[EventType.MARK_PRICE] = EventType.MARK_PRICE
    mark_price: PositiveDecimal
    index_price: PositiveDecimal
    estimated_settle_price: NonnegativeDecimal | None = None
    funding_rate: Decimal
    next_funding_time: AwareDatetime


class DepthLevel(DomainModel):
    model_config = ConfigDict(extra="forbid")

    price: PositiveDecimal
    quantity: NonnegativeDecimal


class DepthEvent(MarketEvent):
    """Depth delta; zero quantity removes a level from a reconciled book.

    Applying these updates as a complete order book requires an initial snapshot
    and exchange-specific sequence reconciliation outside this model.
    """

    event_type: Literal[EventType.DEPTH] = EventType.DEPTH
    first_update_id: SequenceID
    final_update_id: SequenceID
    previous_final_update_id: SequenceID
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    transaction_time: AwareDatetime

    @model_validator(mode="after")
    def ordered_update_ids(self) -> Self:
        if self.first_update_id > self.final_update_id:
            raise ValueError("first_update_id must not exceed final_update_id")
        return self


NormalizedMarketEvent = Annotated[
    TradeEvent | KlineEvent | BookTickerEvent | MarkPriceEvent | DepthEvent,
    Field(discriminator="event_type"),
]


class ConnectionStatus(str, Enum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"


class MarketConnectionState(DomainModel):
    connection_id: Identifier
    event_types: tuple[EventType, ...]
    status: ConnectionStatus
    changed_at: AwareDatetime
    generation: SequenceID = 0
    last_message_at: AwareDatetime | None = None
    reconnect_attempt: SequenceID = 0
    malformed_messages: SequenceID = 0
    reason: SafeReason | None = None


class MarketDataSink(Protocol):
    def publish(self, event: NormalizedMarketEvent, *, connection_id: str) -> None: ...

    def update_connection(self, state: MarketConnectionState) -> None: ...


class MarketDataSource(Protocol):
    async def run(self, sink: MarketDataSink) -> None: ...
