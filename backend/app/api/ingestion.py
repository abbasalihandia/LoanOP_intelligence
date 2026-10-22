"""Trigger ingestion from the simulated sources and inspect the audit trail."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IngestionBatch, RawSourceRecord
from app.db.session import get_db
from app.integration.ingestion import ingest_payloads
from app.integration.sources import MockSourceError, fetch_loan_payloads
from app.integration.vocab import IngestionOutcome, SourceSystem
from app.schemas import IngestionBatchOut, IngestionSummaryOut, RawRecordOut

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/run", response_model=list[IngestionSummaryOut], summary="Pull and ingest simulated feeds")
def run_ingestion(
    source: Literal["ALL", "NCINO_SIM", "LOANIQ_SIM"] = "ALL",
    db: Session = Depends(get_db),
) -> list[IngestionSummaryOut]:
    systems = list(SourceSystem) if source == "ALL" else [SourceSystem(source)]
    summaries = []
    for system in systems:
        try:
            payloads = fetch_loan_payloads(system)
        except MockSourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        summary = ingest_payloads(db, system, payloads, trigger="api")
        summaries.append(IngestionSummaryOut.model_validate(summary))
    return summaries


@router.get("/batches", response_model=list[IngestionBatchOut], summary="Recent ingestion batches")
def list_batches(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IngestionBatchOut]:
    batches = db.scalars(select(IngestionBatch).order_by(IngestionBatch.id.desc()).limit(limit)).all()
    return [IngestionBatchOut.model_validate(b) for b in batches]


@router.get("/raw-records", response_model=list[RawRecordOut], summary="Raw payloads as received")
def list_raw_records(
    outcome: IngestionOutcome | None = None,
    source_system: SourceSystem | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RawRecordOut]:
    stmt = select(RawSourceRecord, IngestionBatch.batch_id).join(
        IngestionBatch, RawSourceRecord.batch_pk == IngestionBatch.id
    )
    if outcome is not None:
        stmt = stmt.where(RawSourceRecord.outcome == outcome.value)
    if source_system is not None:
        stmt = stmt.where(RawSourceRecord.source_system == source_system.value)
    stmt = stmt.order_by(RawSourceRecord.id.desc()).limit(limit)

    return [
        RawRecordOut(
            id=raw.id,
            batch_id=batch_id,
            position=raw.position,
            source_system=raw.source_system,
            external_id=raw.external_id,
            outcome=raw.outcome,
            error=raw.error,
            received_at=raw.received_at,
            payload=raw.payload,
        )
        for raw, batch_id in db.execute(stmt).all()
    ]
