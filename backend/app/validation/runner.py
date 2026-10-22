"""Run the validation engine against the database.

Loads the current upstream/downstream records for every loan, evaluates the
pure rules, grades severity, and hands the findings to the exception engine.
One run = one transaction.
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LoanRecord, MappingRule, ValidationRun, utcnow
from app.exception_engine.service import apply_findings
from app.integration.vocab import DOWNSTREAM, UPSTREAM
from app.validation.config import ValidationConfig
from app.validation.mapping import MappingIndex
from app.validation.model import Finding, LoanSnapshot, MappingRuleView
from app.validation.rules import evaluate_loan
from app.validation.severity import assign_severity


def snapshot_from_record(record: LoanRecord) -> LoanSnapshot:
    return LoanSnapshot(
        loan_id=record.loan_id,
        source_system=record.source_system,
        record_id=record.id,
        version=record.version,
        facility_id=record.facility_id,
        product_type=record.product_type,
        product_code_raw=record.product_code_raw,
        currency=record.currency,
        amount=record.amount,
        maturity_date=record.maturity_date,
        status=record.status,
        mapping_version=record.mapping_version,
        booking_error=record.booking_error,
        normalization_issues=tuple(record.normalization_issues or ()),
    )


def build_mapping_index(session: Session) -> MappingIndex:
    rows = session.scalars(select(MappingRule)).all()
    return MappingIndex(
        MappingRuleView(
            rule_id=r.rule_id,
            mapping_set=r.mapping_set,
            version=r.version,
            source_value=r.source_value,
            target_value=r.target_value,
            status=r.status,
        )
        for r in rows
    )


def collect_findings(session: Session, config: ValidationConfig) -> tuple[int, list[Finding]]:
    """Evaluate every loan with a current record. Returns (loans_evaluated, findings)."""
    records = session.scalars(select(LoanRecord).where(LoanRecord.is_current.is_(True))).all()

    pairs: dict[str, dict[str, LoanSnapshot | None]] = {}
    for record in records:
        side = "up" if record.source_system == UPSTREAM.value else "down"
        if record.source_system not in (UPSTREAM.value, DOWNSTREAM.value):
            continue
        pairs.setdefault(record.loan_id, {"up": None, "down": None})[side] = snapshot_from_record(record)

    index = build_mapping_index(session)
    findings: list[Finding] = []
    for loan_id in sorted(pairs):
        for finding in evaluate_loan(pairs[loan_id]["up"], pairs[loan_id]["down"], index, config):
            finding.severity = assign_severity(finding, config)
            findings.append(finding)
    return len(pairs), findings


def run_validation(session: Session, config: ValidationConfig) -> ValidationRun:
    # Discard any cached rows: statuses may have been changed by other sessions
    # (e.g. an analyst via the API) since this session last read them.
    session.expire_all()
    run = ValidationRun(
        run_id=f"VAL-{utcnow():%Y%m%dT%H%M%S}-{uuid4().hex[:6]}",
        started_at=utcnow(),
        config_fingerprint=config.fingerprint,
    )
    session.add(run)
    try:
        session.flush()
        loans_evaluated, findings = collect_findings(session, config)
        counts = apply_findings(session, findings, run.run_id)

        run.loans_evaluated = loans_evaluated
        run.findings = len(findings)
        run.created = counts.created
        run.redetected = counts.redetected
        run.suppressed = counts.suppressed
        run.no_longer_detected = counts.no_longer_detected
        run.completed_at = utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return run
