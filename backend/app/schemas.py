"""API response models.

Money amounts are Decimal and serialize to JSON as strings (e.g.
"10000000.0") so no precision is lost in transit. All timestamps are UTC.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.exception_engine.status import ExceptionStatus
from app.integration.vocab import SourceSystem
from app.resolution.vocab import AnalystDecision, RecordInError, ResolutionOutcome, RootCauseCategory


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Loans -----------------------------------------------------------------


class LoanRecordOut(ORMModel):
    loan_id: str
    source_system: str
    version: int
    is_current: bool
    facility_id: str | None
    borrower_name: str | None
    product_type: str | None
    product_code_raw: str | None
    currency: str | None
    amount: Decimal | None
    maturity_date: date | None
    status: str | None
    mapping_version: str | None
    booking_error: str | None
    source_updated_at: datetime | None
    ingested_at: datetime
    normalization_issues: list[dict[str, Any]]
    raw_record_id: int


class LoanPairOut(BaseModel):
    """Current upstream and downstream records for one loan."""

    loan_id: str
    upstream: LoanRecordOut | None
    downstream: LoanRecordOut | None


class LoanDetailOut(LoanPairOut):
    upstream_history: list[LoanRecordOut]
    downstream_history: list[LoanRecordOut]


# --- Ingestion -------------------------------------------------------------


class IngestionSummaryOut(ORMModel):
    batch_id: str
    source_system: SourceSystem
    received: int
    created: int
    unchanged: int
    stale: int
    rejected: int
    rejections: list[dict[str, Any]]


class IngestionBatchOut(ORMModel):
    batch_id: str
    source_system: str
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    received: int
    created: int
    unchanged: int
    stale: int
    rejected: int


class RawRecordOut(BaseModel):
    id: int
    batch_id: str
    position: int
    source_system: str
    external_id: str | None
    outcome: str | None
    error: str | None
    received_at: datetime
    payload: Any


# --- Simulated sources -----------------------------------------------------


class MockFeedOut(BaseModel):
    source_system: str
    simulated: bool
    description: str
    records: list[Any]


# --- Reference data --------------------------------------------------------


class MappingRuleOut(ORMModel):
    rule_id: str
    mapping_set: str
    version: str
    field_name: str
    source_system: str
    target_system: str
    source_value: str
    target_value: str
    effective_from: date
    effective_to: date | None
    status: str
    notes: str | None


class AgreementClauseOut(ORMModel):
    clause_id: str
    document_ref: str
    document_type: str
    facility_id: str | None
    loan_id: str | None
    clause_number: str
    title: str
    text: str
    effective_date: date | None


class HistoricalExceptionOut(ORMModel):
    case_id: str
    loan_id: str
    category: str
    field_name: str | None
    source_value: str | None
    target_value: str | None
    description: str
    confirmed_root_cause: str | None
    resolution: str | None
    outcome: str
    resolved_by: str | None
    resolved_at: datetime | None
    keywords: list[str]
    origin: str


# --- Validation ------------------------------------------------------------


class SeverityOverrideOut(BaseModel):
    metric: str
    gte: str
    severity: str


class RuleOut(BaseModel):
    rule_id: str
    category: str
    title: str
    description: str
    base_severity: str
    severity_overrides: list[SeverityOverrideOut]


class ValidationRunOut(ORMModel):
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    config_fingerprint: str
    loans_evaluated: int
    findings: int
    created: int
    redetected: int
    suppressed: int
    no_longer_detected: int


# --- Exceptions ------------------------------------------------------------


class ExceptionOut(ORMModel):
    exception_id: str
    loan_id: str
    rule_id: str
    category: str
    severity: str
    status: str
    side: str
    field_name: str | None
    source_value: str | None
    target_value: str | None
    explanation: str
    still_detected: bool
    detection_count: int
    first_detected_at: datetime
    last_detected_at: datetime
    updated_at: datetime


class StatusChangeOut(ORMModel):
    from_status: str | None
    to_status: str
    actor: str
    reason: str | None
    changed_at: datetime


class ExceptionDetailOut(ExceptionOut):
    details: dict[str, Any]
    first_run_id: str
    last_run_id: str
    created_at: datetime
    upstream_record: LoanRecordOut | None
    downstream_record: LoanRecordOut | None
    status_history: list[StatusChangeOut]
    allowed_next_statuses: list[str]
    can_resolve: bool


class StatusChangeIn(BaseModel):
    to_status: ExceptionStatus
    actor: str = Field(min_length=1, max_length=80, description="Reviewer identifier, e.g. 'analyst.jdoe'")
    reason: str | None = Field(default=None, max_length=2000)


class EvidenceInPackageOut(BaseModel):
    evidence_id: str
    evidence_type: str
    source_reference: str
    source_version: str | None
    loan_id: str | None
    retrieval_method: str
    relevance: str
    score: int | None
    content: dict[str, Any]


class EvidencePackageOut(BaseModel):
    exception_id: str
    loan_id: str
    items: list[EvidenceInPackageOut]
    gaps: list[str]


class EvidenceItemOut(ORMModel):
    evidence_id: str
    evidence_type: str
    source_reference: str
    source_version: str | None
    loan_id: str | None
    content: dict[str, Any]
    content_hash: str
    created_at: datetime


class EvidenceTraceOut(BaseModel):
    evidence: EvidenceItemOut
    traceability_status: str
    traceability_detail: str


class AiStatusOut(BaseModel):
    ollama_base_url: str
    model: str
    reachable: bool
    model_available: bool
    available_models: list[str]
    error_code: str | None
    error: str | None


class InvestigateIn(BaseModel):
    requested_by: str = Field(min_length=1, max_length=80, description="Analyst identifier, e.g. 'analyst.jdoe'")


class InvestigationSummaryOut(ORMModel):
    investigation_id: str
    exception_id: str
    requested_by: str
    model: str
    status: str
    error_code: str | None
    attempts: int
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class InvestigationOut(InvestigationSummaryOut):
    error_message: str | None
    evidence_ids: list[str]
    prompt_sha256: str
    validation_errors: list[dict[str, Any]]
    report: dict[str, Any] | None


class InvestigationAuditOut(InvestigationOut):
    evidence_package: dict[str, Any]
    raw_responses: list[str]


class ResolutionIn(BaseModel):
    resolved_by: str = Field(min_length=1, max_length=80)
    analyst_decision: AnalystDecision
    ai_investigation_id: str | None = Field(default=None, max_length=20)
    ai_cause_index: int | None = Field(default=None, ge=0)
    root_cause_category: RootCauseCategory
    confirmed_root_cause: str = Field(min_length=1, max_length=4000)
    record_in_error: RecordInError
    final_action: str = Field(min_length=1, max_length=4000)
    outcome: ResolutionOutcome
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=4000)


class ResolutionOut(ORMModel):
    resolution_id: str
    exception_id: str
    loan_id: str
    rule_id: str
    category: str
    ai_investigation_id: str | None
    ai_recommendation: dict[str, Any] | None
    ai_cause_index: int | None
    analyst_decision: str
    root_cause_category: str
    confirmed_root_cause: str
    record_in_error: str
    final_action: str
    outcome: str
    evidence_ids: list[str]
    notes: str | None
    resolved_by: str
    resolved_at: datetime
    historical_case_id: str | None


class OptionOut(BaseModel):
    value: str
    label: str


class ResolutionOptionsOut(BaseModel):
    analyst_decision: list[OptionOut]
    root_cause_category: list[OptionOut]
    record_in_error: list[OptionOut]
    outcome: list[OptionOut]


class AuditEventOut(BaseModel):
    at: datetime
    event_type: str
    actor: str
    actor_type: str
    summary: str
    reference: str | None


class ExceptionSummaryOut(BaseModel):
    total: int
    active: int
    active_no_longer_detected: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_category: dict[str, int]
