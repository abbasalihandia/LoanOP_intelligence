"""Record an analyst's resolution.

Rules
  * Only a human reviewer can resolve; RESOLVED is reachable only here.
  * The exception must be in a status that allows RESOLVED
    (UNDER_INVESTIGATION, RECOMMENDATION_GENERATED or ESCALATED).
  * The decision must be consistent with the AI report it refers to:
      AI_ACCEPTED / AI_MODIFIED  -> a SUCCEEDED investigation of this
                                    exception and one of its probable causes
      AI_REJECTED                -> a SUCCEEDED investigation, no cause chosen
      NO_AI_REPORT               -> no investigation referenced
  * Cited evidence must exist and belong to this exception's evidence.
  * Outcome and record_in_error must be coherent.

Effects
  * Stores the resolution with a snapshot of what the AI recommended.
  * Moves the exception to RESOLVED (actor = the reviewer).
  * Adds an ANALYST_CONFIRMED historical case so future investigations on
    other loans can retrieve it. Only analyst-confirmed text is copied;
    AI text is never fed back into history, and the model is not retrained.
  * Never modifies loan records, mappings or bookings.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AiInvestigation,
    EvidenceItem,
    ExceptionEvidenceLink,
    ExceptionRecord,
    ExceptionResolution,
    HistoricalException,
    utcnow,
)
from app.exception_engine.service import change_status
from app.exception_engine.status import SYSTEM_ACTOR_PREFIX, ExceptionStatus, TransitionError, check_transition
from app.resolution.vocab import AnalystDecision, RecordInError, ResolutionOutcome, RootCauseCategory


class ResolutionError(Exception):
    def __init__(self, message: str, http_status: int) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


@dataclass
class ResolutionRequest:
    resolved_by: str
    analyst_decision: AnalystDecision
    root_cause_category: RootCauseCategory
    confirmed_root_cause: str
    record_in_error: RecordInError
    final_action: str
    outcome: ResolutionOutcome
    evidence_ids: list[str]
    ai_investigation_id: str | None = None
    ai_cause_index: int | None = None
    notes: str | None = None


def _fail(message: str, status: int = 422) -> ResolutionError:
    return ResolutionError(message, status)


def _next_resolution_id(session: Session) -> str:
    highest = session.scalar(select(func.max(ExceptionResolution.id))) or 0
    return f"RES-{highest + 1:05d}"


def _ai_snapshot(investigation: AiInvestigation) -> dict:
    report = investigation.report or {}
    return {
        "investigation_id": investigation.investigation_id,
        "model": investigation.model,
        "generated_at": report.get("generated_at"),
        "evidence_sufficiency": report.get("evidence_sufficiency"),
        "root_cause_statement": report.get("root_cause_statement"),
        "probable_causes": report.get("probable_causes", []),
        "overall_assessment": report.get("overall_assessment"),
        "escalation": report.get("escalation"),
        "label": "AI-generated recommendation (not confirmed)",
    }


def _check_ai_reference(session: Session, exception: ExceptionRecord, req: ResolutionRequest) -> AiInvestigation | None:
    if req.analyst_decision == AnalystDecision.NO_AI_REPORT:
        if req.ai_investigation_id or req.ai_cause_index is not None:
            raise _fail("NO_AI_REPORT must not reference an AI investigation or cause.")
        return None

    if not req.ai_investigation_id:
        raise _fail(f"{req.analyst_decision.value} requires ai_investigation_id (the report you reviewed).")
    investigation = session.scalar(
        select(AiInvestigation).where(AiInvestigation.investigation_id == req.ai_investigation_id.strip().upper())
    )
    if investigation is None or investigation.exception_pk != exception.id:
        raise _fail(f"AI investigation {req.ai_investigation_id} does not belong to {exception.exception_id}.")
    if investigation.status != "SUCCEEDED" or not investigation.report:
        raise _fail(f"AI investigation {investigation.investigation_id} did not produce a report.")

    causes = investigation.report.get("probable_causes", [])
    if req.analyst_decision in (AnalystDecision.AI_ACCEPTED, AnalystDecision.AI_MODIFIED):
        if req.ai_cause_index is None or not 0 <= req.ai_cause_index < len(causes):
            raise _fail(
                f"{req.analyst_decision.value} requires ai_cause_index pointing to one of the report's "
                f"{len(causes)} probable cause(s)."
            )
    elif req.ai_cause_index is not None:
        raise _fail("AI_REJECTED must not select an AI cause.")
    return investigation


def _check_evidence(
    session: Session, exception: ExceptionRecord, investigation: AiInvestigation | None, evidence_ids: list[str]
) -> list[str]:
    cleaned = sorted({e.strip().upper() for e in evidence_ids if e.strip()})
    if not cleaned:
        raise _fail("At least one evidence id must be cited for the confirmed root cause.")

    allowed = set(
        session.scalars(
            select(EvidenceItem.evidence_id)
            .join(ExceptionEvidenceLink, ExceptionEvidenceLink.evidence_pk == EvidenceItem.id)
            .where(ExceptionEvidenceLink.exception_pk == exception.id)
        ).all()
    )
    if investigation is not None:
        allowed |= set(investigation.evidence_ids or [])

    unknown = [e for e in cleaned if e not in allowed]
    if unknown:
        raise _fail(
            f"Evidence {', '.join(unknown)} is not part of this exception's evidence. "
            f"Retrieve the evidence package first and cite items from it."
        )
    return cleaned


def _check_coherence(req: ResolutionRequest) -> None:
    if len(req.confirmed_root_cause.strip()) < 10:
        raise _fail("confirmed_root_cause must describe the cause (at least 10 characters).")
    if len(req.final_action.strip()) < 5:
        raise _fail("final_action must describe what was done (at least 5 characters).")
    if req.outcome == ResolutionOutcome.CORRECTED_IN_SOURCE and req.record_in_error in (
        RecordInError.NEITHER, RecordInError.UNDETERMINED
    ):
        raise _fail("CORRECTED_IN_SOURCE requires the record in error to be UPSTREAM, DOWNSTREAM or BOTH.")
    if req.outcome == ResolutionOutcome.NO_CHANGE_REQUIRED and req.record_in_error != RecordInError.NEITHER:
        raise _fail("NO_CHANGE_REQUIRED means neither record was in error; set record_in_error to NEITHER.")


def resolve_exception(session: Session, exception_id: str, req: ResolutionRequest) -> ExceptionResolution:
    reviewer = req.resolved_by.strip()
    if not reviewer:
        raise _fail("resolved_by is required.")
    if reviewer.lower().startswith(SYSTEM_ACTOR_PREFIX):
        raise _fail("Only a human reviewer can resolve an exception.")

    session.expire_all()
    exception = session.scalar(select(ExceptionRecord).where(ExceptionRecord.exception_id == exception_id.strip().upper()))
    if exception is None:
        raise _fail(f"Exception {exception_id} not found", 404)
    if session.scalar(select(ExceptionResolution).where(ExceptionResolution.exception_pk == exception.id)):
        raise _fail(f"{exception.exception_id} is already resolved.", 409)

    try:
        check_transition(ExceptionStatus(exception.status), ExceptionStatus.RESOLVED, reason=None, via_system=True)
    except TransitionError as exc:
        raise _fail(
            f"{exc} Move the exception to UNDER_INVESTIGATION before resolving."
            if exception.status in (ExceptionStatus.OPEN.value, ExceptionStatus.AWAITING_EVIDENCE.value)
            else str(exc),
            409,
        ) from exc

    _check_coherence(req)
    investigation = _check_ai_reference(session, exception, req)
    evidence_ids = _check_evidence(session, exception, investigation, req.evidence_ids)

    now = utcnow()
    resolution = ExceptionResolution(
        resolution_id=_next_resolution_id(session),
        exception_pk=exception.id,
        exception_id=exception.exception_id,
        loan_id=exception.loan_id,
        rule_id=exception.rule_id,
        category=exception.category,
        ai_investigation_id=investigation.investigation_id if investigation else None,
        ai_recommendation=_ai_snapshot(investigation) if investigation else None,
        ai_cause_index=req.ai_cause_index,
        analyst_decision=req.analyst_decision.value,
        root_cause_category=req.root_cause_category.value,
        confirmed_root_cause=req.confirmed_root_cause.strip(),
        record_in_error=req.record_in_error.value,
        final_action=req.final_action.strip(),
        outcome=req.outcome.value,
        evidence_ids=evidence_ids,
        notes=req.notes.strip() if req.notes else None,
        upstream_record_id=exception.upstream_record_id,
        downstream_record_id=exception.downstream_record_id,
        resolved_by=reviewer,
        resolved_at=now,
    )
    session.add(resolution)
    session.flush()

    # Feed the confirmed outcome (analyst text only) back as a historical case.
    case = HistoricalException(
        case_id=f"HX-{resolution.resolution_id}",
        loan_id=exception.loan_id,
        category=exception.category,
        field_name=exception.field_name,
        source_value=exception.source_value,
        target_value=exception.target_value,
        description=exception.explanation,
        confirmed_root_cause=f"[{req.root_cause_category.value}] {req.confirmed_root_cause.strip()}",
        resolution=req.final_action.strip(),
        outcome="RESOLVED",
        resolved_by=reviewer,
        resolved_at=now,
        keywords=[req.root_cause_category.value.lower(), exception.category.lower(), exception.field_name or ""],
        origin="ANALYST_CONFIRMED",
    )
    session.add(case)
    resolution.historical_case_id = case.case_id

    change_status(
        session, exception, ExceptionStatus.RESOLVED, actor=reviewer,
        reason=f"Resolved via {resolution.resolution_id}: {req.outcome.value}", via_system=True,
    )
    session.commit()
    return resolution
