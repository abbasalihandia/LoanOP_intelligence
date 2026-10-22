"""AI investigation endpoints. The browser talks only to these; never to Ollama."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import LlmClient, OllamaClient, model_is_available
from app.ai.errors import LlmError
from app.ai.service import (
    ExceptionClosed,
    ExceptionNotFound,
    InvestigationFailed,
    investigate_exception,
)
from app.config import get_settings
from app.db.models import AiInvestigation
from app.db.session import get_db
from app.exception_engine.service import ActorError
from app.schemas import (
    AiStatusOut,
    InvestigateIn,
    InvestigationAuditOut,
    InvestigationOut,
    InvestigationSummaryOut,
)

router = APIRouter(prefix="/api", tags=["ai investigation"])


def get_llm_client() -> LlmClient:
    """Dependency; tests override it with a fake client."""
    s = get_settings()
    return OllamaClient(
        s.ollama_base_url,
        s.ollama_model,
        timeout_seconds=s.ollama_timeout_seconds,
        temperature=s.ollama_temperature,
        num_ctx=s.ollama_num_ctx,
    )


def get_max_attempts() -> int:
    return get_settings().ollama_max_attempts


@router.get("/ai/status", response_model=AiStatusOut, summary="Is Ollama reachable and the model installed?")
def ai_status(client: LlmClient = Depends(get_llm_client)) -> AiStatusOut:
    base_url = getattr(client, "base_url", get_settings().ollama_base_url)
    try:
        models = client.list_models()
    except LlmError as exc:
        return AiStatusOut(
            ollama_base_url=base_url, model=client.model, reachable=False, model_available=False,
            available_models=[], error_code=exc.code, error=exc.message,
        )
    available = model_is_available(client.model, models)
    return AiStatusOut(
        ollama_base_url=base_url,
        model=client.model,
        reachable=True,
        model_available=available,
        available_models=sorted(models),
        error_code=None if available else "MODEL_NOT_FOUND",
        error=None if available else f"Model '{client.model}' is not installed. Run: ollama pull {client.model}",
    )


@router.post(
    "/exceptions/{exception_id}/investigations",
    response_model=InvestigationOut,
    status_code=201,
    summary="Run an AI investigation for an exception",
)
def create_investigation(
    exception_id: str,
    body: InvestigateIn,
    db: Session = Depends(get_db),
    client: LlmClient = Depends(get_llm_client),
    max_attempts: int = Depends(get_max_attempts),
) -> InvestigationOut:
    try:
        investigation = investigate_exception(
            db, exception_id, requested_by=body.requested_by, client=client, max_attempts=max_attempts
        )
    except ExceptionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExceptionClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvestigationFailed as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error_code": exc.code, "message": exc.message, "investigation_id": exc.investigation_id},
        ) from exc
    return InvestigationOut.model_validate(investigation)


@router.get(
    "/exceptions/{exception_id}/investigations",
    response_model=list[InvestigationSummaryOut],
    summary="AI investigations for an exception (newest first)",
)
def list_investigations(exception_id: str, db: Session = Depends(get_db)) -> list[InvestigationSummaryOut]:
    rows = db.scalars(
        select(AiInvestigation)
        .where(AiInvestigation.exception_id == exception_id.strip().upper())
        .order_by(AiInvestigation.id.desc())
    ).all()
    return [InvestigationSummaryOut.model_validate(r) for r in rows]


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationAuditOut,
    summary="Full investigation record, including evidence snapshot and raw model output",
)
def get_investigation(investigation_id: str, db: Session = Depends(get_db)) -> InvestigationAuditOut:
    row = db.scalar(
        select(AiInvestigation).where(AiInvestigation.investigation_id == investigation_id.strip().upper())
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Investigation {investigation_id} not found")
    return InvestigationAuditOut.model_validate(row)
