"""AI investigation service: evidence -> prompt -> model -> validated report.

Flow
  1. Load the exception (must not be RESOLVED/REJECTED).
  2. Retrieve its evidence package through the Phase 3 evidence engine and
     commit, so no database transaction is held open during the model call.
  3. Call the model with the controlled prompt and the report schema.
  4. Validate (JSON -> Pydantic -> evidence-package semantics).
       invalid output   -> retry with the errors fed back, up to max_attempts
       timeout          -> fail, no retry (another long wait rarely helps)
       unavailable /    -> fail, no retry
       model missing
  5. Store an AiInvestigation row whether it succeeded or failed.
  6. On success only: move the exception to RECOMMENDATION_GENERATED as
     system:ai-investigation. Banking records and mappings are never touched.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import LlmClient
from app.ai.errors import LlmError
from app.ai.policy import policy_flags
from app.ai.prompt import (
    build_messages,
    correction_messages,
    exception_view,
    prompt_sha256,
)
from app.ai.report_validation import ReportValidationError, parse_report
from app.ai.schema import (
    HYPOTHESIS_STATEMENT,
    INSUFFICIENT_STATEMENT,
    AiInvestigationReport,
    AiReportDraft,
    ObservedDiscrepancy,
    ollama_format_schema,
)
from app.db.models import AiInvestigation, ExceptionRecord, utcnow
from app.evidence.package import EvidencePackage
from app.evidence.retrieval import retrieve_evidence
from app.exception_engine.service import ActorError, change_status
from app.exception_engine.status import SYSTEM_ACTOR_PREFIX, TERMINAL, ExceptionStatus

AI_ACTOR = f"{SYSTEM_ACTOR_PREFIX}ai-investigation"

HTTP_STATUS_FOR_ERROR = {
    "OLLAMA_UNAVAILABLE": 503,
    "MODEL_NOT_FOUND": 503,
    "TIMEOUT": 504,
    "LLM_RESPONSE_ERROR": 502,
    "INVALID_OUTPUT": 502,
}


class ExceptionNotFound(LookupError):
    pass


class ExceptionClosed(Exception):
    pass


class InvestigationFailed(Exception):
    def __init__(self, code: str, message: str, investigation_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.investigation_id = investigation_id
        self.http_status = HTTP_STATUS_FOR_ERROR.get(code, 502)


def _next_investigation_id(session: Session) -> str:
    highest = session.scalar(select(func.max(AiInvestigation.id))) or 0
    return f"AI-{highest + 1:05d}"


def assemble_report(
    draft: AiReportDraft, exception: ExceptionRecord, package: EvidencePackage, model: str
) -> AiInvestigationReport:
    """Combine the model's draft with deterministic facts and standard statements."""
    return AiInvestigationReport(
        exception_id=exception.exception_id,
        summary=draft.summary,
        observed_discrepancies=[
            ObservedDiscrepancy(
                field=exception.field_name,
                upstream_value=exception.source_value,
                downstream_value=exception.target_value,
                validation_rule_id=exception.rule_id,
                explanation=exception.explanation,
            )
        ],
        evidence_sufficiency=draft.evidence_sufficiency,
        root_cause_statement=(
            INSUFFICIENT_STATEMENT if draft.evidence_sufficiency == "INSUFFICIENT" else HYPOTHESIS_STATEMENT
        ),
        confirmed_facts=draft.confirmed_facts,
        probable_causes=draft.probable_causes,
        alternative_explanations=draft.alternative_explanations,
        conflicting_evidence=draft.conflicting_evidence,
        recommended_checks=draft.recommended_checks,
        missing_information=draft.missing_information,
        uncertainties=list(draft.uncertainties),
        escalation=draft.escalation,
        overall_assessment=draft.overall_assessment,
        policy_flags=policy_flags(draft),
        evidence_package_ids=sorted(package.ids()),
        model=model,
        generated_at=utcnow().replace(tzinfo=timezone.utc).isoformat(),
    )


@dataclass
class GenerationResult:
    """Outcome of one report generation: evidence -> prompt -> model -> validation."""

    package: EvidencePackage
    prompt_sha256: str
    attempts: int
    raw_responses: list[str]
    attempt_errors: list[dict]
    draft: AiReportDraft | None
    report: dict | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int


def generate_report(
    session: Session, exception: ExceptionRecord, *, client: LlmClient, max_attempts: int
) -> GenerationResult:
    """The shared investigation core used by the workbench and the evaluator.

    Retrieves evidence (committed before the model call, so no database lock
    is held), calls the model with bounded retries on invalid output, and
    validates the result. It does NOT store investigations or change the
    exception's status; callers decide what to persist.
    """
    package = retrieve_evidence(session, exception)
    session.commit()

    messages = build_messages(exception_view(exception), package)
    schema = ollama_format_schema()
    started_at = utcnow()
    t0 = time.perf_counter()

    conversation = messages
    attempts = 0
    raw_responses: list[str] = []
    attempt_errors: list[dict] = []
    draft: AiReportDraft | None = None
    error_code: str | None = None
    error_message: str | None = None

    while attempts < max_attempts:
        attempts += 1
        try:
            raw = client.chat(conversation, schema)
        except LlmError as exc:
            # Timeouts, unavailability and missing models are not retried.
            error_code, error_message = exc.code, exc.message
            break

        raw_responses.append(raw)
        try:
            draft = parse_report(raw, package, exception.exception_id)
            error_code = error_message = None
            break
        except ReportValidationError as exc:
            attempt_errors.append({"attempt": attempts, "errors": exc.errors})
            error_code = "INVALID_OUTPUT"
            error_message = (
                f"The model's report failed validation after {attempts} attempt(s). "
                f"Last errors: {'; '.join(exc.errors[:5])}"
            )
            conversation = correction_messages(messages, raw, exc.errors, package)

    report = (
        assemble_report(draft, exception, package, client.model).model_dump(mode="json") if draft is not None else None
    )
    if report is None and error_code is None:
        error_code, error_message = "INVALID_OUTPUT", "No valid report was produced."

    return GenerationResult(
        package=package,
        prompt_sha256=prompt_sha256(messages),
        attempts=attempts,
        raw_responses=raw_responses,
        attempt_errors=attempt_errors,
        draft=draft,
        report=report,
        error_code=error_code,
        error_message=error_message,
        started_at=started_at,
        completed_at=utcnow(),
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )


def investigate_exception(
    session: Session,
    exception_id: str,
    *,
    requested_by: str,
    client: LlmClient,
    max_attempts: int,
) -> AiInvestigation:
    requested_by = requested_by.strip()
    if not requested_by:
        raise ActorError("requested_by is required.")
    if requested_by.lower().startswith(SYSTEM_ACTOR_PREFIX):
        raise ActorError(f"Identifiers starting with '{SYSTEM_ACTOR_PREFIX}' are reserved for the platform.")

    session.expire_all()
    exception = session.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == exception_id.strip().upper()))
    if exception is None:
        raise ExceptionNotFound(f"Exception {exception_id} not found")
    if exception.status in {s.value for s in TERMINAL}:
        raise ExceptionClosed(f"Exception {exception.exception_id} is {exception.status}; it cannot be investigated.")

    result = generate_report(session, exception, client=client, max_attempts=max_attempts)
    draft = result.draft

    investigation = AiInvestigation(
        investigation_id=_next_investigation_id(session),
        exception_pk=exception.id,
        exception_id=exception.exception_id,
        requested_by=requested_by,
        model=client.model,
        attempts=result.attempts,
        evidence_ids=sorted(result.package.ids()),
        evidence_package=result.package.to_dict(),
        prompt_sha256=result.prompt_sha256,
        raw_responses=result.raw_responses,
        validation_errors=result.attempt_errors,
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_ms=result.duration_ms,
    )

    if result.report is not None:
        investigation.status = "SUCCEEDED"
        investigation.report = result.report
    else:
        investigation.status = "FAILED"
        investigation.error_code = result.error_code
        investigation.error_message = result.error_message

    session.add(investigation)
    session.flush()

    if draft is not None:
        reason = f"AI investigation {investigation.investigation_id} requested by {requested_by}"
        if exception.status != ExceptionStatus.UNDER_INVESTIGATION.value:
            change_status(session, exception, ExceptionStatus.UNDER_INVESTIGATION, actor=AI_ACTOR,
                          reason=reason, via_system=True)
        change_status(session, exception, ExceptionStatus.RECOMMENDATION_GENERATED, actor=AI_ACTOR,
                      reason=reason, via_system=True)

    session.commit()

    if draft is None:
        raise InvestigationFailed(investigation.error_code, investigation.error_message, investigation.investigation_id)
    return investigation
