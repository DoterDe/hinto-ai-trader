from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from src.application.strategy_engine import StrategyEngine
from src.domain.strategies import StrategyEngineStatus, StrategySnapshot

router = APIRouter(prefix="/strategies", tags=["strategies"])


def strategy_engine(request: Request) -> StrategyEngine:
    engine = getattr(request.app.state, "strategy_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Strategies are not initialized")
    return engine


Engine = Annotated[StrategyEngine, Depends(strategy_engine)]


@router.get("/status", response_model=StrategyEngineStatus)
async def strategy_status(engine: Engine) -> StrategyEngineStatus:
    return engine.status()


@router.get("/{symbol}/latest", response_model=StrategySnapshot)
async def latest_strategies(symbol: str, engine: Engine) -> StrategySnapshot:
    try:
        return engine.latest(symbol.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown strategy symbol") from None
