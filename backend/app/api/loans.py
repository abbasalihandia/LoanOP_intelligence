"""Read-only access to normalized, versioned loan records."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LoanRecord
from app.db.session import get_db
from app.integration.vocab import DOWNSTREAM, UPSTREAM
from app.schemas import LoanDetailOut, LoanPairOut, LoanRecordOut

router = APIRouter(prefix="/api/loans", tags=["loans"])


def _out(record: LoanRecord | None) -> LoanRecordOut | None:
    return LoanRecordOut.model_validate(record) if record is not None else None


@router.get("", response_model=list[LoanPairOut], summary="Current upstream/downstream pair per loan")
def list_loans(db: Session = Depends(get_db)) -> list[LoanPairOut]:
    records = db.scalars(
        select(LoanRecord).where(LoanRecord.is_current.is_(True)).order_by(LoanRecord.loan_id)
    ).all()

    pairs: dict[str, dict[str, LoanRecord | None]] = {}
    for record in records:
        side = "upstream" if record.source_system == UPSTREAM.value else "downstream"
        pairs.setdefault(record.loan_id, {"upstream": None, "downstream": None})[side] = record

    return [
        LoanPairOut(loan_id=loan_id, upstream=_out(sides["upstream"]), downstream=_out(sides["downstream"]))
        for loan_id, sides in pairs.items()
    ]


@router.get("/{loan_id}", response_model=LoanDetailOut, summary="One loan with full version history")
def get_loan(loan_id: str, db: Session = Depends(get_db)) -> LoanDetailOut:
    records = db.scalars(
        select(LoanRecord)
        .where(LoanRecord.loan_id == loan_id.strip().upper())
        .order_by(LoanRecord.source_system, LoanRecord.version)
    ).all()
    if not records:
        raise HTTPException(status_code=404, detail=f"Loan {loan_id} not found")

    upstream = [r for r in records if r.source_system == UPSTREAM.value]
    downstream = [r for r in records if r.source_system == DOWNSTREAM.value]

    return LoanDetailOut(
        loan_id=records[0].loan_id,
        upstream=_out(next((r for r in upstream if r.is_current), None)),
        downstream=_out(next((r for r in downstream if r.is_current), None)),
        upstream_history=[LoanRecordOut.model_validate(r) for r in upstream],
        downstream_history=[LoanRecordOut.model_validate(r) for r in downstream],
    )
