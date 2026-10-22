"""FastAPI application entry point.

Run from the backend/ folder:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.ai import router as ai_router
from app.api.evaluation import router as evaluation_router
from app.api.evidence import router as evidence_router
from app.api.exceptions import router as exceptions_router
from app.api.health import router as health_router
from app.api.ingestion import router as ingestion_router
from app.api.loans import router as loans_router
from app.api.mock_sources import router as mock_sources_router
from app.api.reference import router as reference_router
from app.api.resolution import router as resolution_router
from app.api.validation import router as validation_router
from app.config import get_settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Creates missing tables only; never deletes data. Seeding is explicit
    # (python -m app.scripts.seed) so the API never loads data on its own.
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "AI-assisted loan operations exception investigation (POC). "
            "All banking systems and data are simulated."
        ),
        lifespan=lifespan,
    )

    # The Vite dev server proxies /api to this backend, so CORS is only a
    # fallback for direct browser calls. Origins come from configuration.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    app.include_router(health_router)
    app.include_router(mock_sources_router)
    app.include_router(ingestion_router)
    app.include_router(loans_router)
    app.include_router(reference_router)
    app.include_router(validation_router)
    app.include_router(exceptions_router)
    app.include_router(evidence_router)
    app.include_router(ai_router)
    app.include_router(resolution_router)
    app.include_router(evaluation_router)
    return app


app = create_app()
