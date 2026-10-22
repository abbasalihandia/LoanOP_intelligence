"""Build evidence content snapshots and source references from database rows.

Content excludes volatile bookkeeping (ingestion timestamps, detection
counts, status) so that unchanged facts keep the same evidence ID.
"""

from decimal import Decimal
from typing import Any

from app.db.models import AgreementClause, ExceptionRecord, HistoricalException, LoanRecord, MappingRule
from app.validation.rules import RULES


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _dec(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


# --- Loan records ------------------------------------------------------------


def loan_record_reference(record: LoanRecord) -> str:
    return f"{record.source_system}:loan_records:{record.loan_id}:v{record.version}"


def loan_record_content(record: LoanRecord) -> dict[str, Any]:
    return {
        "loan_id": record.loan_id,
        "source_system": record.source_system,
        "record_version": record.version,
        "facility_id": record.facility_id,
        "borrower_name": record.borrower_name,
        "product_type_canonical": record.product_type,
        "product_code_as_received": record.product_code_raw,
        "currency": record.currency,
        "amount": _dec(record.amount),
        "maturity_date": _iso(record.maturity_date),
        "status": record.status,
        "mapping_version": record.mapping_version,
        "booking_error": record.booking_error,
        "source_updated_at_utc": _iso(record.source_updated_at),
        "normalization_issues": list(record.normalization_issues or []),
    }


# --- Validation findings -----------------------------------------------------


def finding_reference(exception: ExceptionRecord) -> str:
    return f"validation:exceptions:{exception.exception_id}"


def finding_content(exception: ExceptionRecord) -> dict[str, Any]:
    spec = RULES.get(exception.rule_id)
    return {
        "exception_id": exception.exception_id,
        "loan_id": exception.loan_id,
        "rule_id": exception.rule_id,
        "rule_title": spec.title if spec else None,
        "category": exception.category,
        "severity": exception.severity,
        "field": exception.field_name,
        "side": exception.side,
        "upstream_value": exception.source_value,
        "downstream_value": exception.target_value,
        "explanation": exception.explanation,
        "details": exception.details or {},
        "note": "Produced by the deterministic validation engine.",
    }


# --- Reference data ----------------------------------------------------------


def mapping_rule_reference(rule: MappingRule) -> str:
    return f"reference:mapping_rules:{rule.rule_id}"


def mapping_rule_content(rule: MappingRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "mapping_set": rule.mapping_set,
        "mapping_version": rule.version,
        "field": rule.field_name,
        "source_system": rule.source_system,
        "target_system": rule.target_system,
        "source_value": rule.source_value,
        "target_value": rule.target_value,
        "effective_from": _iso(rule.effective_from),
        "effective_to": _iso(rule.effective_to),
        "status": rule.status,
        "notes": rule.notes,
    }


def clause_reference(clause: AgreementClause) -> str:
    return f"reference:agreement_clauses:{clause.clause_id}"


def clause_content(clause: AgreementClause) -> dict[str, Any]:
    return {
        "clause_id": clause.clause_id,
        "document_ref": clause.document_ref,
        "document_type": clause.document_type,
        "facility_id": clause.facility_id,
        "loan_id": clause.loan_id,
        "clause_number": clause.clause_number,
        "title": clause.title,
        "text": clause.text,
        "effective_date": _iso(clause.effective_date),
        "note": "Synthetic clause for the proof of concept.",
    }


def historical_case_reference(case: HistoricalException) -> str:
    return f"reference:historical_exceptions:{case.case_id}"


def historical_case_content(case: HistoricalException) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "loan_id": case.loan_id,
        "category": case.category,
        "field": case.field_name,
        "upstream_value": case.source_value,
        "downstream_value": case.target_value,
        "description": case.description,
        "confirmed_root_cause": case.confirmed_root_cause,
        "resolution": case.resolution,
        "outcome": case.outcome,
        "resolved_at_utc": _iso(case.resolved_at),
        "origin": case.origin,
        "note": "A different loan. Shows what happened before; not proof of the current cause.",
    }
