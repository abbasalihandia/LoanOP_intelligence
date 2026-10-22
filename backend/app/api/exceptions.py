"""Exception list, detail, summary and analyst-controlled status changes."""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExceptionRecord, ExceptionStatusChange, LoanRecord
from app.db.session import get_db
from app.exception_engine.service import ActorError, change_status
from app.exception_engine.status import (
    ALLOWED_TRANSITIONS,
    TERMINAL,
    ExceptionStatus,
    TransitionError,
    analyst_next_statuses,
)
from app.schemas import (
    ExceptionDetailOut,
    ExceptionOut,
    ExceptionSummaryOut,
    LoanRecordOut,
    StatusChangeIn,
    StatusChangeOut,
)

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])

_TERMINAL_VALUES = {s.value for s in TERMINAL}


def _get(db: Session, exception_id: str) -> ExceptionRecord:
    record = db.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == exception_id.strip().upper()))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")
    return record


def _detail(db: Session, record: ExceptionRecord) -> ExceptionDetailOut:
    def loan(record_id: int | None) -> LoanRecordOut | None:
        if record_id is None:
            return None
        row = db.get(LoanRecord, record_id)
        return LoanRecordOut.model_validate(row) if row else None

    history = db.scalars(
        select(ExceptionStatusChange)
        .where(ExceptionStatusChange.exception_pk == record.id)
        .order_by(ExceptionStatusChange.id)
    ).all()

    base = ExceptionOut.model_validate(record).model_dump()
    return ExceptionDetailOut(
        **base,
        details=record.details or {},
        first_run_id=record.first_run_id,
        last_run_id=record.last_run_id,
        created_at=record.created_at,
        upstream_record=loan(record.upstream_record_id),
        downstream_record=loan(record.downstream_record_id),
        status_history=[StatusChangeOut.model_validate(h) for h in history],
        allowed_next_statuses=[s.value for s in analyst_next_statuses(ExceptionStatus(record.status))],
        can_resolve=ExceptionStatus.RESOLVED in ALLOWED_TRANSITIONS[ExceptionStatus(record.status)],
    )


@router.get("", response_model=list[ExceptionOut], summary="List exceptions with optional filters")
def list_exceptions(
    status: ExceptionStatus | None = None,
    severity: str | None = None,
    category: str | None = None,
    loan_id: str | None = None,
    active_only: bool = False,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ExceptionOut]:
    stmt = select(ExceptionRecord)
    if status is not None:
        stmt = stmt.where(ExceptionRecord.status == status.value)
    if severity:
        stmt = stmt.where(ExceptionRecord.severity == severity.strip().upper())
    if category:
        stmt = stmt.where(ExceptionRecord.category == category.strip().upper())
    if loan_id:
        stmt = stmt.where(ExceptionRecord.loan_id == loan_id.strip().upper())
    if active_only:
        stmt = stmt.where(ExceptionRecord.status.not_in(_TERMINAL_VALUES))
    rows = db.scalars(stmt.order_by(ExceptionRecord.id).limit(limit)).all()
    return [ExceptionOut.model_validate(r) for r in rows]


@router.get("/summary", response_model=ExceptionSummaryOut, summary="Counts for the dashboard")
def summary(db: Session = Depends(get_db)) -> ExceptionSummaryOut:
    rows = db.scalars(select(ExceptionRecord)).all()
    active = [r for r in rows if r.status not in _TERMINAL_VALUES]
    return ExceptionSummaryOut(
        total=len(rows),
        active=len(active),
        active_no_longer_detected=sum(1 for r in active if not r.still_detected),
        by_status=dict(Counter(r.status for r in rows)),
        by_severity=dict(Counter(r.severity for r in active)),
        by_category=dict(Counter(r.category for r in active)),
    )


@router.get("/{exception_id}", response_model=ExceptionDetailOut, summary="Exception detail with history")
def get_exception(exception_id: str, db: Session = Depends(get_db)) -> ExceptionDetailOut:
    return _detail(db, _get(db, exception_id))


@router.patch("/{exception_id}/status", response_model=ExceptionDetailOut, summary="Change status (analyst)")
def update_status(exception_id: str, body: StatusChangeIn, db: Session = Depends(get_db)) -> ExceptionDetailOut:
    record = _get(db, exception_id)
    try:
        change_status(db, record, body.to_status, actor=body.actor, reason=body.reason)
    except ActorError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return _detail(db, record)
