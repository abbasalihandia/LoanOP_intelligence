"""Ingestion: raw payload -> audit record -> normalized, versioned loan record.

For every payload received:
  1. A RawSourceRecord is stored exactly as received (audit trail).
  2. The payload is normalized. Structural failures are REJECTED with a
     reason; nothing else is created.
  3. The normalized content is compared with the loan's current version:
       identical content           -> UNCHANGED (no new version)
       older source timestamp      -> STALE     (ignored, current kept)
       otherwise                   -> CREATED   (new version, becomes current)

A batch is committed as one transaction; on an unexpected error the whole
batch is rolled back.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IngestionBatch, LoanRecord, RawSourceRecord, utcnow
from app.integration.normalizers import NORMALIZERS, IngestionRejected, NormalizedLoan
from app.integration.vocab import IngestionOutcome, SourceSystem


@dataclass
class IngestionSummary:
    batch_id: str
    source_system: SourceSystem
    received: int = 0
    created: int = 0
    unchanged: int = 0
    stale: int = 0
    rejected: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)


def new_batch_id(source_system: SourceSystem) -> str:
    return f"BATCH-{utcnow():%Y%m%dT%H%M%S}-{source_system.value}-{uuid4().hex[:6]}"


def ingest_payloads(
    session: Session,
    source_system: SourceSystem,
    payloads: Iterable[Any],
    trigger: str = "api",
) -> IngestionSummary:
    normalize = NORMALIZERS[source_system]
    session.expire_all()  # read current versions fresh, not from this session's cache

    batch = IngestionBatch(
        batch_id=new_batch_id(source_system),
        source_system=source_system.value,
        trigger=trigger,
        started_at=utcnow(),
    )
    session.add(batch)

    try:
        session.flush()
        summary = IngestionSummary(batch_id=batch.batch_id, source_system=source_system)

        for position, payload in enumerate(payloads):
            summary.received += 1
            raw = RawSourceRecord(
                batch_pk=batch.id,
                position=position,
                source_system=source_system.value,
                payload=payload,
                received_at=utcnow(),
            )
            session.add(raw)

            try:
                loan = normalize(payload)
            except IngestionRejected as exc:
                raw.outcome = IngestionOutcome.REJECTED.value
                raw.error = exc.reason
                summary.rejected += 1
                summary.rejections.append({"position": position, "reason": exc.reason})
                continue

            raw.external_id = loan.loan_id
            session.flush()  # assigns raw.id

            outcome = _store_version(session, loan, raw.id)
            raw.outcome = outcome.value
            if outcome is IngestionOutcome.CREATED:
                summary.created += 1
            elif outcome is IngestionOutcome.UNCHANGED:
                summary.unchanged += 1
            elif outcome is IngestionOutcome.STALE:
                summary.stale += 1

        batch.received = summary.received
        batch.created = summary.created
        batch.unchanged = summary.unchanged
        batch.stale = summary.stale
        batch.rejected = summary.rejected
        batch.completed_at = utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise

    return summary


def _store_version(session: Session, loan: NormalizedLoan, raw_record_id: int) -> IngestionOutcome:
    same_loan = (
        LoanRecord.loan_id == loan.loan_id,
        LoanRecord.source_system == loan.source_system.value,
    )
    current = session.scalar(select(LoanRecord).where(*same_loan, LoanRecord.is_current.is_(True)))
    content_hash = loan.content_hash()

    if current is not None:
        if current.content_hash == content_hash:
            return IngestionOutcome.UNCHANGED
        if (
            loan.source_updated_at is not None
            and current.source_updated_at is not None
            and loan.source_updated_at < current.source_updated_at
        ):
            return IngestionOutcome.STALE
        current.is_current = False

    latest_version = session.scalar(select(func.max(LoanRecord.version)).where(*same_loan)) or 0

    session.add(
        LoanRecord(
            loan_id=loan.loan_id,
            source_system=loan.source_system.value,
            version=latest_version + 1,
            is_current=True,
            facility_id=loan.facility_id,
            borrower_name=loan.borrower_name,
            product_type=loan.product_type.value if loan.product_type else None,
            product_code_raw=loan.product_code_raw,
            currency=loan.currency,
            amount=loan.amount,
            maturity_date=loan.maturity_date,
            status=loan.status,
            mapping_version=loan.mapping_version,
            booking_error=loan.booking_error,
            source_updated_at=loan.source_updated_at,
            content_hash=content_hash,
            normalization_issues=[issue.to_dict() for issue in loan.issues],
            raw_record_id=raw_record_id,
            ingested_at=utcnow(),
        )
    )
    session.flush()  # make the new version visible to the next payload in this batch
    return IngestionOutcome.CREATED
