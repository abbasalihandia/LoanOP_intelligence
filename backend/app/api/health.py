"""Health-check endpoint.

Used by the frontend to confirm the backend is reachable, and later by
any tooling that needs a liveness check.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import __version__
from app.config import Settings, get_settings

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(description="Always 'ok' when the service responds.")
    service: str = Field(description="Service name from configuration.")
    version: str = Field(description="Backend application version.")
    environment: str = Field(description="Deployment environment label, e.g. 'local'.")
    data_mode: Literal["synthetic"] = Field(
        description="All banking data and integrations in this POC are simulated."
    )
    server_time_utc: datetime = Field(description="Current server time (timezone-aware, UTC).")


@router.get("/health", response_model=HealthResponse, summary="Backend health check")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        data_mode="synthetic",
        server_time_utc=datetime.now(timezone.utc),
    )
