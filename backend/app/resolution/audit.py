"""Chronological audit trail for one exception.

Built from the source-of-truth tables (status history, AI investigations,
evidence links, resolution) rather than a duplicate log, so it cannot drift.
Every event is labelled with who acted: ANALYST, SYSTEM (deterministic
platform), AI (the model) or AI_SERVICE (the platform acting on an AI
result). This keeps AI output and human decisions visibly distinct.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AiInvestigation,
    ExceptionEvidenceLink,
    ExceptionRecord,
    ExceptionResolution,
    ExceptionStatusChange,
)
from app.exception_engine.status import SYSTEM_ACTOR_PREFIX

AI_SERVICE_ACTOR = f"{SYSTEM_ACTOR_PREFIX}ai-investigation"


@dataclass(frozen=True)
class AuditEvent:
    at: datetime
    event_type: str
    actor: str
    actor_type: str  # ANALYST / SYSTEM / AI / AI_SERVICE
    summary: str
    reference: str | None = None


def _actor_type(actor: str) -> str:
    if actor == AI_SERVICE_ACTOR:
        return "AI_SERVICE"
    if actor.lower().startswith(SYSTEM_ACTOR_PREFIX):
        return "SYSTEM"
    return "ANALYST"


def build_audit_trail(session: Session, exception: ExceptionRecord) -> list[AuditEvent]:
    events: list[tuple[datetime, int, AuditEvent]] = []

    for change in session.scalars(
        select(ExceptionStatusChange)
        .where(ExceptionStatusChange.exception_pk == exception.id)
        .order_by(ExceptionStatusChange.id)
    ):
        created = change.from_status is None
        summary = (
            f"Exception created ({change.to_status})" if created
            else f"Status {change.from_status} → {change.to_status}"
        )
        if change.reason:
            summary += f". {change.reason}"
        events.append((change.changed_at, 2, AuditEvent(
            change.changed_at, "EXCEPTION_CREATED" if created else "STATUS_CHANGED",
            change.actor, _actor_type(change.actor), summary,
        )))

    retrieved_at = session.scalar(
        select(func.max(ExceptionEvidenceLink.retrieved_at)).where(ExceptionEvidenceLink.exception_pk == exception.id)
    )
    if retrieved_at is not None:
        count = session.scalar(
            select(func.count(ExceptionEvidenceLink.id)).where(ExceptionEvidenceLink.exception_pk == exception.id)
        )
        events.append((retrieved_at, 0, AuditEvent(
            retrieved_at, "EVIDENCE_RETRIEVED", "system:evidence", "SYSTEM",
            f"Latest evidence package retrieved ({count} items).",
        )))

    for inv in session.scalars(
        select(AiInvestigation).where(AiInvestigation.exception_pk == exception.id).order_by(AiInvestigation.id)
    ):
        events.append((inv.started_at, 1, AuditEvent(
            inv.started_at, "AI_INVESTIGATION_REQUESTED", inv.requested_by, _actor_type(inv.requested_by),
            f"AI investigation requested ({inv.model}).", inv.investigation_id,
        )))
        finished = inv.completed_at or inv.started_at
        if inv.status == "SUCCEEDED":
            sufficiency = (inv.report or {}).get("evidence_sufficiency", "?")
            summary = f"AI report generated in {inv.attempts} attempt(s); evidence sufficiency {sufficiency}. Not a confirmed finding."
        else:
            summary = f"AI investigation failed [{inv.error_code}] after {inv.attempts} attempt(s)."
        events.append((finished, 1, AuditEvent(
            finished, f"AI_INVESTIGATION_{inv.status}", inv.model, "AI", summary, inv.investigation_id,
        )))

    resolution = session.scalar(select(ExceptionResolution).where(ExceptionResolution.exception_pk == exception.id))
    if resolution is not None:
        basis = f" (reviewed {resolution.ai_investigation_id})" if resolution.ai_investigation_id else ""
        events.append((resolution.resolved_at, 1, AuditEvent(
            resolution.resolved_at, "RESOLUTION_RECORDED", resolution.resolved_by, "ANALYST",
            f"{resolution.analyst_decision}{basis}: {resolution.root_cause_category}; "
            f"record in error {resolution.record_in_error}; outcome {resolution.outcome}.",
            resolution.resolution_id,
        )))

    events.sort(key=lambda e: (e[0], e[1]))
    return [e[2] for e in events]
