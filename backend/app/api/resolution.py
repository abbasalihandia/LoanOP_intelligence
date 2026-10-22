"""Analyst resolution workflow and audit trail (Phase 6)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExceptionRecord, ExceptionResolution
from app.db.session import get_db
from app.resolution.audit import build_audit_trail
from app.resolution.service import ResolutionError, ResolutionRequest, resolve_exception
from app.resolution.vocab import LABELS
from app.schemas import AuditEventOut, OptionOut, ResolutionIn, ResolutionOptionsOut, ResolutionOut

router = APIRouter(prefix="/api", tags=["resolution and audit"])


@router.get("/resolution/options", response_model=ResolutionOptionsOut, summary="Values and labels for the resolution form")
def resolution_options() -> ResolutionOptionsOut:
    return ResolutionOptionsOut(**{
        group: [OptionOut(value=str(value), label=label) for value, label in labels.items()]
        for group, labels in LABELS.items()
    })


@router.post(
    "/exceptions/{exception_id}/resolution",
    response_model=ResolutionOut,
    status_code=201,
    summary="Record the analyst-confirmed resolution",
)
def create_resolution(exception_id: str, body: ResolutionIn, db: Session = Depends(get_db)) -> ResolutionOut:
    try:
        resolution = resolve_exception(db, exception_id, ResolutionRequest(**body.model_dump()))
    except ResolutionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
    return ResolutionOut.model_validate(resolution)


@router.get("/exceptions/{exception_id}/resolution", response_model=ResolutionOut, summary="Resolution of an exception")
def get_resolution(exception_id: str, db: Session = Depends(get_db)) -> ResolutionOut:
    row = db.scalar(select(ExceptionResolution).where(ExceptionResolution.exception_id == exception_id.strip().upper()))
    if row is None:
        raise HTTPException(status_code=404, detail=f"{exception_id} has no resolution")
    return ResolutionOut.model_validate(row)


@router.get("/resolutions", response_model=list[ResolutionOut], summary="All resolutions (newest first)")
def list_resolutions(
    analyst_decision: str | None = None,
    root_cause_category: str | None = None,
    db: Session = Depends(get_db),
) -> list[ResolutionOut]:
    stmt = select(ExceptionResolution)
    if analyst_decision:
        stmt = stmt.where(ExceptionResolution.analyst_decision == analyst_decision.strip().upper())
    if root_cause_category:
        stmt = stmt.where(ExceptionResolution.root_cause_category == root_cause_category.strip().upper())
    rows = db.scalars(stmt.order_by(ExceptionResolution.id.desc())).all()
    return [ResolutionOut.model_validate(r) for r in rows]


@router.get("/exceptions/{exception_id}/audit", response_model=list[AuditEventOut], summary="Chronological audit trail")
def get_audit(exception_id: str, db: Session = Depends(get_db)) -> list[AuditEventOut]:
    record = db.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == exception_id.strip().upper()))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")
    return [AuditEventOut(**event.__dict__) for event in build_audit_trail(db, record)]
