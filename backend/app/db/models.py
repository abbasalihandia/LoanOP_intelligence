"""ORM models for Phase 1.

Ingestion audit
  IngestionBatch     one run of a source feed
  RawSourceRecord    every payload exactly as received, with its outcome

Normalized, versioned loan data
  LoanRecord         canonical view of one loan in one source system;
                     a new version is created only when content changes

Reference data (synthetic)
  MappingRule        upstream -> downstream field-value mappings, versioned
  AgreementClause    facility agreement and amendment clauses
  HistoricalException previously resolved (or closed) cases

All timestamps are stored as naive UTC.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Current time as naive UTC (the storage convention for this database)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DecimalString(TypeDecorator[Decimal]):
    """Stores Decimal values as exact text.

    SQLite has no native decimal type; storing amounts as REAL would introduce
    floating-point error into financial comparisons.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return format(Decimal(value), "f")

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Ingestion audit
# ---------------------------------------------------------------------------


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(80), unique=True)
    source_system: Mapped[str] = mapped_column(String(20), index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    received: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    stale: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)


class RawSourceRecord(Base):
    __tablename__ = "raw_source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_pk: Mapped[int] = mapped_column(ForeignKey("ingestion_batches.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source_system: Mapped[str] = mapped_column(String(20), index=True)
    external_id: Mapped[str | None] = mapped_column(String(40), index=True)
    payload: Mapped[Any] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str | None] = mapped_column(String(20), index=True)
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Normalized loan records
# ---------------------------------------------------------------------------


class LoanRecord(Base):
    __tablename__ = "loan_records"
    __table_args__ = (
        UniqueConstraint("source_system", "loan_id", "version", name="uq_loan_source_version"),
        Index("ix_loan_current", "loan_id", "source_system", "is_current"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    source_system: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    facility_id: Mapped[str | None] = mapped_column(String(40))
    borrower_name: Mapped[str | None] = mapped_column(String(200))
    product_type: Mapped[str | None] = mapped_column(String(40))
    product_code_raw: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[Decimal | None] = mapped_column(DecimalString(40))
    maturity_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(40))

    # Downstream-only fields (None for upstream records).
    mapping_version: Mapped[str | None] = mapped_column(String(40))
    booking_error: Mapped[str | None] = mapped_column(Text)

    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    content_hash: Mapped[str] = mapped_column(String(64))
    normalization_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    raw_record_id: Mapped[int] = mapped_column(ForeignKey("raw_source_records.id"))
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class MappingRule(Base):
    __tablename__ = "mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(40), unique=True)
    mapping_set: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[str] = mapped_column(String(40), index=True)
    field_name: Mapped[str] = mapped_column(String(60))
    source_system: Mapped[str] = mapped_column(String(20))
    target_system: Mapped[str] = mapped_column(String(20))
    source_value: Mapped[str] = mapped_column(String(120))
    target_value: Mapped[str] = mapped_column(String(120))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)


class AgreementClause(Base):
    __tablename__ = "agreement_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clause_id: Mapped[str] = mapped_column(String(40), unique=True)
    document_ref: Mapped[str] = mapped_column(String(40), index=True)
    document_type: Mapped[str] = mapped_column(String(30))
    facility_id: Mapped[str | None] = mapped_column(String(40), index=True)
    loan_id: Mapped[str | None] = mapped_column(String(40), index=True)
    clause_number: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)


class HistoricalException(Base):
    __tablename__ = "historical_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(40), unique=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    field_name: Mapped[str | None] = mapped_column(String(60))
    source_value: Mapped[str | None] = mapped_column(String(200))
    target_value: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    confirmed_root_cause: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(30))
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(30), default="SEED_LEGACY")


# ---------------------------------------------------------------------------
# Validation and exceptions (Phase 2)
# ---------------------------------------------------------------------------


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    config_fingerprint: Mapped[str] = mapped_column(String(64))

    loans_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    findings: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    redetected: Mapped[int] = mapped_column(Integer, default=0)
    suppressed: Mapped[int] = mapped_column(Integer, default=0)
    no_longer_detected: Mapped[int] = mapped_column(Integer, default=0)


class ExceptionRecord(Base):
    """One discrepancy under management.

    `fingerprint` identifies the problem (loan + rule + field + side) across
    runs; `exception_id` is the stable, human-facing identifier.
    """

    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_id: Mapped[str] = mapped_column(String(20), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)
    value_signature: Mapped[str] = mapped_column(String(16))

    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    side: Mapped[str] = mapped_column(String(12))
    field_name: Mapped[str | None] = mapped_column(String(60))
    source_value: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    upstream_record_id: Mapped[int | None] = mapped_column(ForeignKey("loan_records.id"))
    downstream_record_id: Mapped[int | None] = mapped_column(ForeignKey("loan_records.id"))

    status: Mapped[str] = mapped_column(String(30), index=True)
    still_detected: Mapped[bool] = mapped_column(Boolean, default=True)
    detection_count: Mapped[int] = mapped_column(Integer, default=1)
    first_run_id: Mapped[str] = mapped_column(String(80))
    last_run_id: Mapped[str] = mapped_column(String(80))
    first_detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExceptionStatusChange(Base):
    """Append-only history of every status change, including creation."""

    __tablename__ = "exception_status_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_pk: Mapped[int] = mapped_column(ForeignKey("exceptions.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Evidence (Phase 3)
# ---------------------------------------------------------------------------


class EvidenceItem(Base):
    """An immutable snapshot of one piece of evidence.

    The same source with the same content always maps to the same
    evidence_id, so IDs cited in AI reports remain resolvable to exactly what
    was shown. If the source content changes, a new evidence item is created.
    """

    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("source_reference", "content_hash", name="uq_evidence_source_content"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(20), unique=True)
    evidence_type: Mapped[str] = mapped_column(String(30), index=True)
    source_reference: Mapped[str] = mapped_column(String(200), index=True)
    source_version: Mapped[str | None] = mapped_column(String(80))
    loan_id: Mapped[str | None] = mapped_column(String(40), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExceptionEvidenceLink(Base):
    """Why a piece of evidence was retrieved for an exception (latest retrieval)."""

    __tablename__ = "exception_evidence"
    __table_args__ = (UniqueConstraint("exception_pk", "evidence_pk", name="uq_exception_evidence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_pk: Mapped[int] = mapped_column(ForeignKey("exceptions.id"), index=True)
    evidence_pk: Mapped[int] = mapped_column(ForeignKey("evidence_items.id"))
    position: Mapped[int] = mapped_column(Integer)
    retrieval_method: Mapped[str] = mapped_column(String(40))
    relevance: Mapped[str] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# AI investigations (Phase 4) — kept separate from analyst resolutions (Phase 6)
# ---------------------------------------------------------------------------


class AiInvestigation(Base):
    """One AI investigation attempt, successful or not, with full audit data."""

    __tablename__ = "ai_investigations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(String(20), unique=True)
    exception_pk: Mapped[int] = mapped_column(ForeignKey("exceptions.id"), index=True)
    exception_id: Mapped[str] = mapped_column(String(20), index=True)
    requested_by: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))

    status: Mapped[str] = mapped_column(String(20), index=True)  # SUCCEEDED / FAILED
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_package: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    raw_responses: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Resolutions (Phase 6) — the analyst's confirmed outcome, separate from AI
# ---------------------------------------------------------------------------


class ExceptionResolution(Base):
    """The analyst-confirmed resolution of one exception.

    Stores what the AI recommended (a snapshot of the reviewed report) next
    to what the analyst decided and confirmed, so the two can never be
    confused. Resolving never modifies loan records or mappings: corrections
    happen in the source systems under their own controls.
    """

    __tablename__ = "exception_resolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resolution_id: Mapped[str] = mapped_column(String(20), unique=True)
    exception_pk: Mapped[int] = mapped_column(ForeignKey("exceptions.id"), unique=True)
    exception_id: Mapped[str] = mapped_column(String(20), index=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_id: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40), index=True)

    # What the AI recommended (None when no AI report was reviewed).
    ai_investigation_id: Mapped[str | None] = mapped_column(String(20))
    ai_recommendation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ai_cause_index: Mapped[int | None] = mapped_column(Integer)

    # What the analyst decided and confirmed.
    analyst_decision: Mapped[str] = mapped_column(String(20), index=True)
    root_cause_category: Mapped[str] = mapped_column(String(40), index=True)
    confirmed_root_cause: Mapped[str] = mapped_column(Text)
    record_in_error: Mapped[str] = mapped_column(String(12))
    final_action: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(30))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    # Record versions the exception referred to when resolved (for recurrence checks).
    upstream_record_id: Mapped[int | None] = mapped_column(ForeignKey("loan_records.id"))
    downstream_record_id: Mapped[int | None] = mapped_column(ForeignKey("loan_records.id"))

    resolved_by: Mapped[str] = mapped_column(String(80))
    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    historical_case_id: Mapped[str | None] = mapped_column(String(40))


# ---------------------------------------------------------------------------
# Evaluation (Phase 7) — separate from operational investigations
# ---------------------------------------------------------------------------


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(20), unique=True)
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    max_attempts: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # RUNNING / COMPLETED / ABORTED
    scenario_count: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_pk: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    exception_id: Mapped[str | None] = mapped_column(String(20))
    loan_id: Mapped[str] = mapped_column(String(40))
    rule_id: Mapped[str] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # SUCCEEDED / FAILED / SKIPPED
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_package: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_responses: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
