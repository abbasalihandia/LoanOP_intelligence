"""Read-only access to evaluation runs (Phase 7). Runs are started from the CLI."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, EvaluationRun
from app.db.session import get_db

router = APIRouter(prefix="/api/evaluations", tags=["evaluation"])


class EvaluationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: str
    model: str
    prompt_version: str
    max_attempts: int
    status: str
    scenario_count: int
    started_at: datetime
    completed_at: datetime | None
    summary: dict[str, Any] | None


class EvaluationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scenario_id: str
    title: str
    exception_id: str | None
    status: str
    error_code: str | None
    attempts: int
    duration_ms: int | None
    score: float
    checks: list[dict[str, Any]]
    metrics: dict[str, Any]
    report: dict[str, Any] | None


class EvaluationDetailOut(EvaluationRunOut):
    results: list[EvaluationResultOut]


@router.get("", response_model=list[EvaluationRunOut])
def list_runs(db: Session = Depends(get_db)) -> list[EvaluationRunOut]:
    rows = db.scalars(select(EvaluationRun).order_by(EvaluationRun.id.desc())).all()
    return [EvaluationRunOut.model_validate(r) for r in rows]


@router.get("/{run_id}", response_model=EvaluationDetailOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> EvaluationDetailOut:
    run = db.scalar(select(EvaluationRun).where(EvaluationRun.run_id == run_id.strip().upper()))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Evaluation {run_id} not found")
    results = db.scalars(select(EvaluationResult).where(EvaluationResult.run_pk == run.id)
                         .order_by(EvaluationResult.id)).all()
    return EvaluationDetailOut(
        **EvaluationRunOut.model_validate(run).model_dump(),
        results=[EvaluationResultOut.model_validate(r) for r in results],
    )
