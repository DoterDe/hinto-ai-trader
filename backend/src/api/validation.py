"""Reads of startup-loaded research telemetry; no report computation or writes."""

from fastapi import APIRouter, Request

from src.application.validation_telemetry import ValidationSnapshot, ValidationStatus, empty_validation

router = APIRouter(prefix="/validation", tags=["validation"])


def snapshot(request: Request) -> ValidationSnapshot:
    return getattr(request.app.state, "validation_snapshot", None) or empty_validation()


@router.get("/status", response_model=ValidationStatus)
async def status(request: Request) -> ValidationStatus:
    return snapshot(request).status


@router.get("/latest", response_model=ValidationSnapshot)
async def latest(request: Request) -> ValidationSnapshot:
    return snapshot(request)
