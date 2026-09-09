from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from src.application.decision_engine import DecisionEngine, DecisionSourceError
from src.domain.decisions import DecisionEngineStatus, DecisionRecord

router = APIRouter(prefix="/decisions", tags=["decisions"])


def decision_engine(request: Request) -> DecisionEngine:
    engine = getattr(request.app.state, "decision_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Decisions are not initialized")
    return engine


Engine = Annotated[DecisionEngine, Depends(decision_engine)]


@router.get("/status", response_model=DecisionEngineStatus)
async def decision_status(engine: Engine) -> DecisionEngineStatus:
    try:
        return engine.status()
    except DecisionSourceError:
        raise HTTPException(status_code=503, detail="Decisions cannot read strategy state") from None


@router.get("/{symbol}/latest", response_model=DecisionRecord)
async def latest_decision(symbol: str, engine: Engine) -> DecisionRecord:
    try:
        return engine.latest(symbol.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown decision symbol") from None
    except DecisionSourceError:
        raise HTTPException(status_code=503, detail="Decisions cannot read strategy state") from None
