"""Check that an evidence item still matches its source.

CURRENT        the source exists and produces identical content
SOURCE_CHANGED the source exists but its content now differs from the snapshot
SOURCE_MISSING the source no longer exists

Loan record versions are immutable, so their evidence stays CURRENT even
after newer versions arrive. Reference data can change on re-seed.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgreementClause,
    EvidenceItem,
    ExceptionRecord,
    HistoricalException,
    LoanRecord,
    MappingRule,
)
from app.evidence import content as c
from app.evidence.package import content_hash


@dataclass(frozen=True)
class TraceResult:
    status: str
    detail: str


def _current_content(session: Session, reference: str) -> dict[str, Any] | None:
    parts = reference.split(":")
    # "<SOURCE_SYSTEM>:loan_records:<LOAN_ID>:v<N>"  (see content.loan_record_reference)
    if len(parts) == 4 and parts[1] == "loan_records":
        source_system, _, loan_id, version = parts
        record = session.scalar(
            select(LoanRecord).where(
                LoanRecord.source_system == source_system,
                LoanRecord.loan_id == loan_id,
                LoanRecord.version == int(version.lstrip("v")),
            )
        )
        return c.loan_record_content(record) if record else None

    if len(parts) != 3:
        return None
    _, table, key = parts
    if table == "exceptions":
        row = session.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == key))
        return c.finding_content(row) if row else None
    if table == "mapping_rules":
        row = session.scalar(select(MappingRule).where(MappingRule.rule_id == key))
        return c.mapping_rule_content(row) if row else None
    if table == "agreement_clauses":
        row = session.scalar(select(AgreementClause).where(AgreementClause.clause_id == key))
        return c.clause_content(row) if row else None
    if table == "historical_exceptions":
        row = session.scalar(select(HistoricalException).where(HistoricalException.case_id == key))
        return c.historical_case_content(row) if row else None
    return None


def verify_evidence(session: Session, item: EvidenceItem) -> TraceResult:
    current = _current_content(session, item.source_reference)
    if current is None:
        return TraceResult("SOURCE_MISSING", f"Source {item.source_reference} no longer exists.")
    if content_hash(current) != item.content_hash:
        return TraceResult(
            "SOURCE_CHANGED",
            f"Source {item.source_reference} has changed since this evidence was captured; "
            f"the snapshot shows what was used at the time.",
        )
    return TraceResult("CURRENT", "Snapshot matches the current source.")
