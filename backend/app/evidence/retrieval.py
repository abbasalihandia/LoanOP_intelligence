"""Assemble the evidence package for one exception.

Retrieval order (also the order evidence is shown to analysts and the model):
  1. the exception's own validation finding
  2. the upstream and downstream record versions the rule evaluated
  3. other active findings on the same loan
  4. mapping rules (product-type exceptions only): recorded version + active
  5. agreement clauses for the loan/facility that relate to the field
  6. similar historical cases (top 3 above a minimum score)

Plus deterministic gaps: things an investigator would want that are absent.
Retrieval is idempotent: the same sources yield the same evidence IDs.
"""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AgreementClause,
    EvidenceItem,
    ExceptionEvidenceLink,
    ExceptionRecord,
    HistoricalException,
    LoanRecord,
    MappingRule,
    utcnow,
)
from app.evidence import content as c
from app.evidence.package import (
    EvidencePackage,
    EvidenceType,
    PackagedEvidence,
    RetrievalMethod,
    content_hash,
)
from app.evidence.relevance import (
    HISTORY_MAX_RESULTS,
    HISTORY_MIN_SCORE,
    clause_keyword_matches,
    is_contractual_field,
    score_historical_case,
)
from app.exception_engine.status import TERMINAL

_TERMINAL_VALUES = [s.value for s in TERMINAL]


def _register(
    session: Session,
    evidence_type: EvidenceType,
    source_reference: str,
    source_version: str | None,
    loan_id: str | None,
    content: dict[str, Any],
) -> EvidenceItem:
    """Return the evidence item for (source, content), creating it if new."""
    digest = content_hash(content)
    item = session.scalar(
        select(EvidenceItem).where(
            EvidenceItem.source_reference == source_reference,
            EvidenceItem.content_hash == digest,
        )
    )
    if item is not None:
        return item

    highest = session.scalar(select(func.max(EvidenceItem.id))) or 0
    item = EvidenceItem(
        evidence_id=f"EV-{highest + 1:05d}",
        evidence_type=evidence_type.value,
        source_reference=source_reference,
        source_version=source_version,
        loan_id=loan_id,
        content=content,
        content_hash=digest,
        created_at=utcnow(),
    )
    session.add(item)
    session.flush()
    return item


class _Collector:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.entries: list[tuple[EvidenceItem, RetrievalMethod, str, int | None]] = []
        self._seen: set[int] = set()

    def add(
        self,
        evidence_type: EvidenceType,
        reference: str,
        version: str | None,
        loan_id: str | None,
        content: dict[str, Any],
        method: RetrievalMethod,
        relevance: str,
        score: int | None = None,
    ) -> None:
        item = _register(self.session, evidence_type, reference, version, loan_id, content)
        if item.id in self._seen:
            return
        self._seen.add(item.id)
        self.entries.append((item, method, relevance, score))


def retrieve_evidence(session: Session, exception: ExceptionRecord) -> EvidencePackage:
    """Build (and record links for) the evidence package. Caller commits."""
    collector = _Collector(session)
    gaps: list[str] = []
    loan_id = exception.loan_id

    # 1. The finding itself.
    collector.add(
        EvidenceType.VALIDATION_FINDING, c.finding_reference(exception), exception.value_signature,
        loan_id, c.finding_content(exception), RetrievalMethod.EXCEPTION_SUBJECT,
        f"The validation finding under investigation ({exception.rule_id}).",
    )

    # 2. Evaluated record versions.
    upstream = session.get(LoanRecord, exception.upstream_record_id) if exception.upstream_record_id else None
    downstream = session.get(LoanRecord, exception.downstream_record_id) if exception.downstream_record_id else None
    for record, etype, label in (
        (upstream, EvidenceType.UPSTREAM_RECORD, "upstream"),
        (downstream, EvidenceType.DOWNSTREAM_RECORD, "downstream"),
    ):
        if record is None:
            gaps.append(f"No {label} record exists for {loan_id}.")
            continue
        collector.add(
            etype, c.loan_record_reference(record), f"v{record.version}", loan_id,
            c.loan_record_content(record), RetrievalMethod.EVALUATED_RECORD,
            f"The {label} record version (v{record.version}) evaluated by the validation rule.",
        )

    # 3. Other active findings on the same loan.
    related = session.scalars(
        select(ExceptionRecord)
        .where(
            ExceptionRecord.loan_id == loan_id,
            ExceptionRecord.id != exception.id,
            ExceptionRecord.status.not_in(_TERMINAL_VALUES),
        )
        .order_by(ExceptionRecord.id)
    ).all()
    for other in related:
        collector.add(
            EvidenceType.VALIDATION_FINDING, c.finding_reference(other), other.value_signature, loan_id,
            c.finding_content(other), RetrievalMethod.SAME_LOAN_FINDING,
            f"Another active finding on the same loan ({other.exception_id}, {other.rule_id}).",
        )

    # 4. Mapping rules for product-type exceptions.
    if exception.field_name == "product_type":
        _add_mapping_evidence(session, collector, gaps, upstream, downstream, loan_id)

    # 5. Agreement clauses.
    _add_clause_evidence(session, collector, gaps, exception, upstream, downstream)

    # 6. Similar historical cases.
    _add_historical_evidence(session, collector, gaps, exception)

    # Replace the stored links with this retrieval.
    session.query(ExceptionEvidenceLink).filter(ExceptionEvidenceLink.exception_pk == exception.id).delete()
    now = utcnow()
    for position, (item, method, relevance, score) in enumerate(collector.entries):
        session.add(
            ExceptionEvidenceLink(
                exception_pk=exception.id, evidence_pk=item.id, position=position,
                retrieval_method=method.value, relevance=relevance, score=score, retrieved_at=now,
            )
        )
    session.flush()

    return EvidencePackage(
        exception_id=exception.exception_id,
        loan_id=loan_id,
        items=tuple(
            PackagedEvidence(
                evidence_id=item.evidence_id,
                evidence_type=item.evidence_type,
                source_reference=item.source_reference,
                source_version=item.source_version,
                loan_id=item.loan_id,
                retrieval_method=method.value,
                relevance=relevance,
                score=score,
                content=item.content,
            )
            for item, method, relevance, score in collector.entries
        ),
        gaps=tuple(gaps),
    )


def mapping_timeline_note(rule: MappingRule, downstream: LoanRecord | None) -> str:
    """Deterministic timeline: where the downstream record's last update falls
    relative to the rule's effective period. Uses 'last updated' precisely;
    it is not necessarily the original booking date."""
    if downstream is None or downstream.source_updated_at is None:
        return " Timeline: the downstream record has no update timestamp to compare."
    updated = downstream.source_updated_at.date()
    start, end = rule.effective_from, rule.effective_to
    period = f"{start.isoformat()} to {end.isoformat() if end else 'open-ended'}"
    if updated < start:
        position = f"before this rule became effective on {start.isoformat()}"
    elif end is not None and updated > end:
        position = f"after this rule's effective period ended on {end.isoformat()}"
    else:
        position = f"within this rule's effective period ({period})"
    return f" Timeline: the downstream record was last updated on {updated.isoformat()}, {position}."


def _add_mapping_evidence(
    session: Session,
    collector: _Collector,
    gaps: list[str],
    upstream: LoanRecord | None,
    downstream: LoanRecord | None,
    loan_id: str,
) -> None:
    source_value = upstream.product_code_raw if upstream else None
    if not source_value:
        gaps.append("The upstream product value is unavailable, so mapping rules cannot be looked up.")
        return

    recorded = None
    version = downstream.mapping_version if downstream else None
    if downstream is not None and not version:
        gaps.append("The downstream record does not state which mapping version was applied.")
    if version:
        recorded = session.scalar(
            select(MappingRule).where(
                MappingRule.version == version,
                func.lower(MappingRule.source_value) == source_value.strip().lower(),
            )
        )
        if recorded is None:
            gaps.append(f"No mapping rule for '{source_value}' was found in mapping version '{version}'.")
        else:
            collector.add(
                EvidenceType.MAPPING_RULE, c.mapping_rule_reference(recorded), recorded.version, None,
                c.mapping_rule_content(recorded), RetrievalMethod.MAPPING_LOOKUP,
                f"The rule for '{source_value}' in the mapping version recorded on the downstream record ({version})."
                + mapping_timeline_note(recorded, downstream),
            )

    active_stmt = select(MappingRule).where(
        MappingRule.status == "ACTIVE",
        func.lower(MappingRule.source_value) == source_value.strip().lower(),
    )
    if recorded is not None:
        active_stmt = active_stmt.where(MappingRule.mapping_set == recorded.mapping_set)
    for active in session.scalars(active_stmt.order_by(MappingRule.rule_id)).all():
        collector.add(
            EvidenceType.MAPPING_RULE, c.mapping_rule_reference(active), active.version, None,
            c.mapping_rule_content(active), RetrievalMethod.MAPPING_LOOKUP,
            f"The currently active rule for '{source_value}' ({active.version})."
            + mapping_timeline_note(active, downstream),
        )


def _add_clause_evidence(
    session: Session,
    collector: _Collector,
    gaps: list[str],
    exception: ExceptionRecord,
    upstream: LoanRecord | None,
    downstream: LoanRecord | None,
) -> None:
    if not is_contractual_field(exception.field_name):
        return
    facility_ids = {r.facility_id for r in (upstream, downstream) if r is not None and r.facility_id}
    conditions = [AgreementClause.loan_id == exception.loan_id]
    if facility_ids:
        conditions.append(AgreementClause.facility_id.in_(facility_ids))
    clauses = session.scalars(select(AgreementClause).where(or_(*conditions)).order_by(AgreementClause.clause_id)).all()

    if not clauses:
        gaps.append(f"No facility agreement or amendment clauses are on file for {exception.loan_id}.")
        return

    matched = 0
    for clause in clauses:
        keywords = clause_keyword_matches(exception.field_name, clause.title, clause.text)
        if not keywords:
            continue
        matched += 1
        collector.add(
            EvidenceType.AGREEMENT_CLAUSE, c.clause_reference(clause), clause.document_ref, clause.loan_id,
            c.clause_content(clause), RetrievalMethod.CLAUSE_KEYWORD_MATCH,
            f"{clause.document_type} {clause.document_ref} clause {clause.clause_number}; "
            f"matched on: {', '.join(keywords)}.",
            score=len(keywords),
        )
    if matched == 0:
        gaps.append(
            f"Agreement clauses are on file for {exception.loan_id}, but none relate to '{exception.field_name}'."
        )


def _add_historical_evidence(
    session: Session, collector: _Collector, gaps: list[str], exception: ExceptionRecord
) -> None:
    scored = []
    for case in session.scalars(select(HistoricalException)).all():
        if case.loan_id == exception.loan_id:
            continue  # history of the same loan would be circular here
        similarity = score_historical_case(
            exc_category=exception.category, exc_field=exception.field_name,
            exc_source_value=exception.source_value, exc_target_value=exception.target_value,
            case_category=case.category, case_field=case.field_name,
            case_source_value=case.source_value, case_target_value=case.target_value,
        )
        if similarity.score >= HISTORY_MIN_SCORE:
            scored.append((similarity, case))

    scored.sort(key=lambda pair: (-pair[0].score, pair[1].case_id))
    if not scored:
        gaps.append("No sufficiently similar historical cases were found.")
        return

    for similarity, case in scored[:HISTORY_MAX_RESULTS]:
        collector.add(
            EvidenceType.HISTORICAL_CASE, c.historical_case_reference(case), case.case_id, case.loan_id,
            c.historical_case_content(case), RetrievalMethod.HISTORICAL_SIMILARITY,
            f"Similar past case on another loan (score {similarity.score}: {'; '.join(similarity.reasons)}). "
            f"Not proof of the current cause.",
            score=similarity.score,
        )
