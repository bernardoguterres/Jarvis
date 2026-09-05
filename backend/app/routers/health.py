from __future__ import annotations

from fastapi import APIRouter

from app.schemas import HealthRead

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthRead)
def health() -> HealthRead:
    return HealthRead(status="ok")
