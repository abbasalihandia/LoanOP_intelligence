"""Evidence retrieval and traceability endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvidenceItem, ExceptionRecord
from app.db.session import get_db
from app.evidence.retrieval import retrieve_evidence
from app.evidence.traceability import verify_evidence
from app.schemas import EvidenceInPackageOut, EvidenceItemOut, EvidencePackageOut, EvidenceTraceOut

router = APIRouter(prefix="/api", tags=["evidence"])


@router.get(
    "/exceptions/{exception_id}/evidence",
    response_model=EvidencePackageOut,
    summary="Retrieve the evidence package for an exception",
)
def get_exception_evidence(exception_id: str, db: Session = Depends(get_db)) -> EvidencePackageOut:
    record = db.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == exception_id.strip().upper()))
    if record is None:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")
    # Retrieval is idempotent: it registers new evidence snapshots only when
    # sources have changed, and refreshes the exception's evidence links.
    package = retrieve_evidence(db, record)
    db.commit()
    return EvidencePackageOut(
        exception_id=package.exception_id,
        loan_id=package.loan_id,
        items=[EvidenceInPackageOut(**asdict(item)) for item in package.items],
        gaps=list(package.gaps),
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceTraceOut, summary="Evidence item with traceability check")
def get_evidence(evidence_id: str, db: Session = Depends(get_db)) -> EvidenceTraceOut:
    item = db.scalar(select(EvidenceItem).where(EvidenceItem.evidence_id == evidence_id.strip().upper()))
    if item is None:
        raise HTTPException(status_code=404, detail=f"Evidence {evidence_id} not found")
    trace = verify_evidence(db, item)
    return EvidenceTraceOut(
        evidence=EvidenceItemOut.model_validate(item),
        traceability_status=trace.status,
        traceability_detail=trace.detail,
    )
