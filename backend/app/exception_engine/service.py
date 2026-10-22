"""Exception persistence: create, re-detect, suppress, and change status.

Re-detection rules for a finding with a given fingerprint, based on the most
recent exception with that fingerprint:

  none exists                          -> create a new exception (OPEN)
  latest is active (not terminal)      -> update it in place (re-detected)
  latest is closed, same values        -> suppress (analyst already closed this exact discrepancy)
                                          EXCEPT: resolved as CORRECTED_IN_SOURCE and newer
                                          record versions still show it -> new exception
                                          (the correction did not land)
  latest is closed, different values   -> create a new exception (it recurred)

Active exceptions that are not found in a run are flagged still_detected=False.
They are NEVER closed automatically; closing is an analyst decision.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ExceptionRecord, ExceptionResolution, ExceptionStatusChange, utcnow
from app.exception_engine.status import (
    SYSTEM_ACTOR_PREFIX,
    TERMINAL,
    ExceptionStatus,
    check_transition,
)
from app.validation.model import Finding

VALIDATION_ACTOR = f"{SYSTEM_ACTOR_PREFIX}validation"
_TERMINAL_VALUES = [s.value for s in TERMINAL]


@dataclass
class ApplyCounts:
    created: int = 0
    redetected: int = 0
    suppressed: int = 0
    no_longer_detected: int = 0


def _next_exception_id(session: Session) -> str:
    highest = session.scalar(select(func.max(ExceptionRecord.id))) or 0
    return f"EXC-{highest + 1:05d}"


def _copy_finding(record: ExceptionRecord, finding: Finding) -> None:
    record.severity = finding.severity or "MEDIUM"
    record.side = finding.side.value
    record.field_name = finding.field_name
    record.source_value = finding.source_value
    record.target_value = finding.target_value
    record.value_signature = finding.value_signature
    record.explanation = finding.explanation
    record.details = finding.details
    record.upstream_record_id = finding.upstream_record_id
    record.downstream_record_id = finding.downstream_record_id


def _correction_did_not_land(session: Session, latest: ExceptionRecord, finding: Finding) -> str | None:
    """A RESOLVED exception whose analyst said 'corrected in source' must
    resurface if NEWER record versions still show the same discrepancy.

    Returns a recurrence note, or None to keep suppressing (closed by the
    analyst, or no newer data has arrived since the resolution yet).
    """
    if latest.status != ExceptionStatus.RESOLVED.value:
        return None
    resolution = session.scalar(
        select(ExceptionResolution).where(ExceptionResolution.exception_pk == latest.id)
    )
    if resolution is None or resolution.outcome != "CORRECTED_IN_SOURCE":
        return None
    newer_data = (
        finding.upstream_record_id != resolution.upstream_record_id
        or finding.downstream_record_id != resolution.downstream_record_id
    )
    if not newer_data:
        return None  # awaiting the corrected feed
    return (
        f"recurrence of {latest.exception_id}: resolved as corrected in source ({resolution.resolution_id}), "
        f"but newer record versions still show the same discrepancy"
    )


def apply_findings(session: Session, findings: Iterable[Finding], run_id: str) -> ApplyCounts:
    """Persist findings from one validation run. Caller commits."""
    counts = ApplyCounts()
    detected_ids: set[int] = set()
    now = utcnow()

    for finding in findings:
        latest = session.scalar(
            select(ExceptionRecord)
            .where(ExceptionRecord.fingerprint == finding.fingerprint)
            .order_by(ExceptionRecord.id.desc())
            .limit(1)
        )

        if latest is not None and latest.status not in _TERMINAL_VALUES:
            _copy_finding(latest, finding)
            latest.still_detected = True
            latest.detection_count += 1
            latest.last_detected_at = now
            latest.last_run_id = run_id
            latest.updated_at = now
            detected_ids.add(latest.id)
            counts.redetected += 1
            continue

        recurrence_note = None
        if latest is not None and latest.value_signature == finding.value_signature:
            recurrence_note = _correction_did_not_land(session, latest, finding)
            if recurrence_note is None:
                counts.suppressed += 1
                continue

        record = ExceptionRecord(
            exception_id=_next_exception_id(session),
            fingerprint=finding.fingerprint,
            loan_id=finding.loan_id,
            rule_id=finding.rule_id,
            category=finding.category,
            status=ExceptionStatus.OPEN.value,
            still_detected=True,
            detection_count=1,
            first_run_id=run_id,
            last_run_id=run_id,
            first_detected_at=now,
            last_detected_at=now,
            created_at=now,
            updated_at=now,
        )
        _copy_finding(record, finding)
        session.add(record)
        session.flush()  # assigns record.id, so the next exception ID is correct

        reason = f"Detected by {finding.rule_id} in {run_id}"
        if recurrence_note is not None:
            reason += f"; {recurrence_note}"
        elif latest is not None:
            reason += f"; recurrence of {latest.exception_id} ({latest.status}) with different values"
        session.add(
            ExceptionStatusChange(
                exception_pk=record.id,
                from_status=None,
                to_status=ExceptionStatus.OPEN.value,
                actor=VALIDATION_ACTOR,
                reason=reason,
                changed_at=now,
            )
        )
        detected_ids.add(record.id)
        counts.created += 1

    active = session.scalars(
        select(ExceptionRecord).where(
            ExceptionRecord.status.not_in(_TERMINAL_VALUES),
            ExceptionRecord.still_detected.is_(True),
        )
    ).all()
    for record in active:
        if record.id not in detected_ids:
            record.still_detected = False
            record.updated_at = now
            counts.no_longer_detected += 1

    session.flush()
    return counts


class ActorError(ValueError):
    """The actor identifier is not acceptable."""


def change_status(
    session: Session,
    record: ExceptionRecord,
    target: ExceptionStatus,
    *,
    actor: str,
    reason: str | None,
    via_system: bool = False,
) -> ExceptionStatusChange:
    """Validate and apply a status change, appending to the history. Caller commits."""
    actor = actor.strip()
    if not actor:
        raise ActorError("Actor is required.")
    if actor.lower().startswith(SYSTEM_ACTOR_PREFIX) and not via_system:
        raise ActorError(f"Actor identifiers starting with '{SYSTEM_ACTOR_PREFIX}' are reserved for the platform.")

    current = ExceptionStatus(record.status)
    check_transition(current, target, reason=reason, via_system=via_system)

    now = utcnow()
    change = ExceptionStatusChange(
        exception_pk=record.id,
        from_status=current.value,
        to_status=target.value,
        actor=actor,
        reason=reason.strip() if reason else None,
        changed_at=now,
    )
    record.status = target.value
    record.updated_at = now
    session.add(change)
    session.flush()
    return change
