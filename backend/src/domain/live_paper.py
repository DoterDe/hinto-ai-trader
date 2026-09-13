"""Immutable live public-data / virtual-only runtime contracts."""

from enum import Enum
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from src.domain.market_data import KlineEvent, MarketSymbol, SafeReason, SequenceID
from src.domain.models import Identifier
from src.domain.paper_portfolio import PortfolioModel
from src.domain.paper_portfolio import PaperPnl, PaperPosition, PaperPositionClose, PortfolioDecisionRecord
from src.domain.features import FeatureSnapshot
from src.domain.strategies import StrategySnapshot


class LivePaperStatus(str, Enum):
    DISABLED = "DISABLED"
    STARTING = "STARTING"
    WARMING_UP = "WARMING_UP"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class LivePaperEvent(PortfolioModel):
    event_id: Identifier
    timestamp: AwareDatetime
    category: Literal["runtime", "feed", "batch", "portfolio"]
    severity: Literal["info", "warning", "error"]
    symbol: MarketSymbol | None = None
    reason: SafeReason
    explanation: Annotated[str, Field(min_length=1, max_length=500)]
    related_id: Identifier | None = None


class LiveBarBatch(PortfolioModel):
    boundary: AwareDatetime
    bars: tuple[KlineEvent, ...]
    missing_symbols: tuple[MarketSymbol, ...] = ()
    conflicting_symbols: tuple[MarketSymbol, ...] = ()
    reason: Literal["complete", "timeout", "conflict"]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        symbols = tuple(bar.symbol for bar in self.bars)
        if symbols != tuple(sorted(set(symbols))):
            raise ValueError("batch bars must be unique and sorted")
        for values in (self.missing_symbols, self.conflicting_symbols):
            if values != tuple(sorted(set(values))):
                raise ValueError("batch diagnostics must be unique and sorted")
        if set(symbols) & set(self.missing_symbols) or not set(self.conflicting_symbols) <= set(self.missing_symbols):
            raise ValueError("conflicting symbols must remain missing")
        if any(not bar.is_closed for bar in self.bars):
            raise ValueError("live batch requires finalized candles")
        if self.reason == "complete" and self.missing_symbols:
            raise ValueError("complete batch cannot contain missing symbols")
        return self


class LivePosition(PortfolioModel):
    position: PaperPosition
    unrealized_net_pnl: Decimal | None


class LiveClose(PortfolioModel):
    position: PaperPosition
    close: PaperPositionClose


class LiveAnalysis(PortfolioModel):
    boundary: AwareDatetime
    published_at: AwareDatetime
    received_at: AwareDatetime
    connection_id: Identifier
    connection_generation: SequenceID
    features: FeatureSnapshot
    strategy: StrategySnapshot
    portfolio: PortfolioDecisionRecord
