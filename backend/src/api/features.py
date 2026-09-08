from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from src.application.feature_engine import FeatureEngine
from src.domain.features import FeatureEngineStatus, FeatureSnapshot


router = APIRouter(prefix="/features", tags=["features"])


def feature_engine(request: Request) -> FeatureEngine:
    engine = getattr(request.app.state, "feature_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Features are not initialized")
    return engine


Engine = Annotated[FeatureEngine, Depends(feature_engine)]


@router.get("/status", response_model=FeatureEngineStatus)
async def feature_status(engine: Engine) -> FeatureEngineStatus:
    return engine.status()


@router.get("/{symbol}/latest", response_model=FeatureSnapshot)
async def latest_features(symbol: str, engine: Engine) -> FeatureSnapshot:
    try:
        return engine.latest(symbol.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown feature symbol") from None
