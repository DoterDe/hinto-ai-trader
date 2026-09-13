from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BeforeValidator

from src.application.explanations import MODULES, TERMS, ExplanationTerm, ModuleExplanation
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_telemetry import (
    LiveDashboardSnapshot, LivePortfolioSnapshot, LivePositionsSnapshot, LiveStatusSnapshot,
    dashboard_snapshot, portfolio_snapshot, positions_snapshot, status_snapshot,
)
from src.domain.live_paper import LiveAnalysis, LivePaperEvent
from src.domain.paper_portfolio import PaperPortfolioCurvePoint

router = APIRouter(tags=['virtual paper telemetry'])


def runtime(request: Request) -> LivePaperCoordinator:
    value = getattr(request.app.state, 'live_paper_coordinator', None)
    if value is None:
        raise HTTPException(status_code=503, detail='Virtual paper runtime is not initialized')
    return value


def integer_limit(value: object) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    if type(value) is int:
        return value
    raise ValueError('limit must be a positive integer')


Runtime = Annotated[LivePaperCoordinator, Depends(runtime)]
Limit = Annotated[int, Query(ge=1, le=1000), BeforeValidator(integer_limit)]


@router.get('/paper/snapshot', response_model=LiveDashboardSnapshot)
async def paper_snapshot(value: Runtime, limit: Limit = 100) -> LiveDashboardSnapshot:
    return dashboard_snapshot(value, limit)


@router.get('/paper/status', response_model=LiveStatusSnapshot)
async def paper_status(value: Runtime) -> LiveStatusSnapshot:
    return status_snapshot(value)


@router.get('/paper/portfolio', response_model=LivePortfolioSnapshot)
async def paper_portfolio(value: Runtime) -> LivePortfolioSnapshot:
    return portfolio_snapshot(value)


@router.get('/paper/positions', response_model=LivePositionsSnapshot)
async def paper_positions(value: Runtime, limit: Limit = 100) -> LivePositionsSnapshot:
    return positions_snapshot(value, limit)


@router.get('/paper/decisions', response_model=tuple[LiveAnalysis, ...])
async def paper_decisions(value: Runtime, limit: Limit = 100) -> tuple[LiveAnalysis, ...]:
    return tuple(reversed(tuple(value.decisions)[-limit:]))


@router.get('/paper/events', response_model=tuple[LivePaperEvent, ...])
async def paper_events(value: Runtime, limit: Limit = 100) -> tuple[LivePaperEvent, ...]:
    return tuple(reversed(tuple(value.events)[-limit:]))


@router.get('/paper/curve', response_model=tuple[PaperPortfolioCurvePoint, ...])
async def paper_curve(value: Runtime, limit: Limit = 500) -> tuple[PaperPortfolioCurvePoint, ...]:
    return tuple(value.portfolio.curve)[-limit:]


@router.get('/explain/modules', response_model=tuple[ModuleExplanation, ...])
async def modules() -> tuple[ModuleExplanation, ...]:
    return MODULES


@router.get('/explain/terms', response_model=tuple[ExplanationTerm, ...])
async def terms() -> tuple[ExplanationTerm, ...]:
    return TERMS
