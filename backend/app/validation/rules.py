"""Deterministic validation rules.

Every rule has a stable ID. Findings describe *what differs*, never *which
side is right*: the engine reports upstream and downstream values neutrally
and leaves the judgement to investigation (evidence, AI, analyst).

Rule order within a loan (also the order exception IDs are assigned):
  1. required fields and data types, upstream then downstream
  2. upstream/downstream comparisons
  3. mapping configuration checks
  4. booking status checks
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.validation.config import ValidationConfig
from app.validation.mapping import MappingIndex
from app.validation.model import Finding, LoanSnapshot, Side


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    category: str
    title: str
    description: str


_SPECS = [
    RuleSpec("RULE-REQ-001", "MISSING_FIELD", "Required field missing",
             "A mandatory field is absent from the upstream or downstream record."),
    RuleSpec("RULE-TYPE-001", "DATA_TYPE", "Invalid field value",
             "A field was supplied but could not be parsed (amount, date, currency or product code)."),
    RuleSpec("RULE-PRODUCT-001", "PRODUCT_MISMATCH", "Product type mismatch",
             "Upstream and downstream product types differ after normalization."),
    RuleSpec("RULE-CCY-001", "CURRENCY_MISMATCH", "Currency mismatch",
             "Upstream and downstream currencies differ."),
    RuleSpec("RULE-AMT-001", "AMOUNT_MISMATCH", "Amount mismatch",
             "Upstream and downstream amounts differ by more than the configured tolerance."),
    RuleSpec("RULE-MAT-001", "MATURITY_MISMATCH", "Maturity date mismatch",
             "Upstream and downstream maturity dates differ by more than the configured tolerance."),
    RuleSpec("RULE-MAP-001", "MAPPING_INCONSISTENCY", "Mapping not applied as configured",
             "The downstream product code differs from what the mapping version recorded on the downstream record prescribes."),
    RuleSpec("RULE-MAP-002", "MAPPING_INCONSISTENCY", "Retired mapping produces a different result",
             "The downstream record references a retired mapping version whose result differs from the currently active mapping."),
    RuleSpec("RULE-MAP-003", "MAPPING_INCONSISTENCY", "Mapping rule not found",
             "The recorded mapping version does not exist, or has no rule for the upstream value."),
    RuleSpec("RULE-BOOK-001", "BOOKING_FAILURE", "Downstream booking failed",
             "The downstream system reports a failed booking status."),
    RuleSpec("RULE-BOOK-002", "MISSING_DOWNSTREAM", "Approved loan not booked",
             "An approved upstream loan has no downstream record."),
    RuleSpec("RULE-BOOK-003", "ORPHAN_DOWNSTREAM", "Downstream record without upstream",
             "A downstream record has no corresponding upstream record."),
]

RULES: dict[str, RuleSpec] = {spec.rule_id: spec for spec in _SPECS}

# Canonical field -> attribute holding its "was it supplied?" value.
_PRESENCE_ATTR = {
    "facility_id": "facility_id",
    "product_type": "product_code_raw",
    "currency": "currency",
    "amount": "amount",
    "maturity_date": "maturity_date",
    "status": "status",
    "mapping_version": "mapping_version",
}

REQUIRED_FIELDS: dict[Side, tuple[str, ...]] = {
    Side.UPSTREAM: ("facility_id", "product_type", "currency", "amount", "maturity_date", "status"),
    Side.DOWNSTREAM: ("facility_id", "product_type", "currency", "amount", "maturity_date", "status", "mapping_version"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _display(snapshot: LoanSnapshot | None, field_name: str) -> str | None:
    """Value as an analyst would recognise it (raw product code, ISO date, plain decimal)."""
    if snapshot is None:
        return None
    value: Any = getattr(snapshot, _PRESENCE_ATTR.get(field_name, field_name), None)
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _finding(
    rule_id: str,
    side: Side,
    field_name: str | None,
    upstream: LoanSnapshot | None,
    downstream: LoanSnapshot | None,
    explanation: str,
    details: dict[str, Any] | None = None,
    source_value: str | None = None,
    target_value: str | None = None,
) -> Finding:
    loan_id = (upstream or downstream).loan_id  # type: ignore[union-attr]
    return Finding(
        loan_id=loan_id,
        rule_id=rule_id,
        category=RULES[rule_id].category,
        side=side,
        field_name=field_name,
        source_value=source_value,
        target_value=target_value,
        explanation=explanation,
        details=details or {},
        upstream_record_id=upstream.record_id if upstream else None,
        downstream_record_id=downstream.record_id if downstream else None,
    )


def _money(value: Decimal) -> str:
    """Display form for explanations: thousands separators, two decimals."""
    return format(value.quantize(Decimal("0.01")), ",f")


def _label(side: Side, snapshot: LoanSnapshot) -> str:
    return f"{side.value.lower()} ({snapshot.source_system})"


# ---------------------------------------------------------------------------
# 1. Required fields and data types
# ---------------------------------------------------------------------------


def check_required_and_types(
    side: Side, snapshot: LoanSnapshot, upstream: LoanSnapshot | None, downstream: LoanSnapshot | None
) -> list[Finding]:
    findings: list[Finding] = []

    for issue in snapshot.normalization_issues:
        field_name = str(issue.get("field"))
        raw = issue.get("raw_value")
        raw_text = None if raw is None else str(raw)
        findings.append(
            _finding(
                "RULE-TYPE-001", side, field_name, upstream, downstream,
                f"The {_label(side, snapshot)} value for '{field_name}' is {raw_text!r}, "
                f"which could not be interpreted: {issue.get('issue')}.",
                details={"raw_value": raw, "issue": issue.get("issue")},
                source_value=raw_text if side is Side.UPSTREAM else _display(upstream, field_name),
                target_value=raw_text if side is Side.DOWNSTREAM else _display(downstream, field_name),
            )
        )

    for field_name in REQUIRED_FIELDS[side]:
        present = getattr(snapshot, _PRESENCE_ATTR[field_name]) is not None
        if present or snapshot.issue_for(field_name) is not None:
            continue  # supplied (an unparseable value is reported by RULE-TYPE-001 instead)
        findings.append(
            _finding(
                "RULE-REQ-001", side, field_name, upstream, downstream,
                f"The required field '{field_name}' is missing from the {_label(side, snapshot)} record.",
                source_value=None if side is Side.UPSTREAM else _display(upstream, field_name),
                target_value=None if side is Side.DOWNSTREAM else _display(downstream, field_name),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# 2. Upstream/downstream comparisons
# ---------------------------------------------------------------------------


def compare_records(upstream: LoanSnapshot, downstream: LoanSnapshot, config: ValidationConfig) -> list[Finding]:
    findings: list[Finding] = []
    up_sys, down_sys = upstream.source_system, downstream.source_system

    if upstream.product_type and downstream.product_type and upstream.product_type != downstream.product_type:
        findings.append(
            _finding(
                "RULE-PRODUCT-001", Side.BOTH, "product_type", upstream, downstream,
                f"Product type differs: upstream ({up_sys}) '{upstream.product_code_raw}' "
                f"[{upstream.product_type}] vs downstream ({down_sys}) '{downstream.product_code_raw}' "
                f"[{downstream.product_type}].",
                details={
                    "upstream_canonical": upstream.product_type,
                    "downstream_canonical": downstream.product_type,
                },
                source_value=upstream.product_code_raw,
                target_value=downstream.product_code_raw,
            )
        )

    if upstream.currency and downstream.currency and upstream.currency != downstream.currency:
        findings.append(
            _finding(
                "RULE-CCY-001", Side.BOTH, "currency", upstream, downstream,
                f"Currency differs: upstream ({up_sys}) {upstream.currency} vs downstream ({down_sys}) {downstream.currency}.",
                source_value=upstream.currency,
                target_value=downstream.currency,
            )
        )

    if upstream.amount is not None and downstream.amount is not None:
        difference = downstream.amount - upstream.amount
        if abs(difference) > config.amount_tolerance:
            metrics: dict[str, Any] = {"abs_difference": format(abs(difference), "f")}
            if upstream.amount != 0:
                pct = (abs(difference) / abs(upstream.amount) * 100).quantize(Decimal("0.01"))
                metrics["pct_difference"] = format(pct, "f")
            findings.append(
                _finding(
                    "RULE-AMT-001", Side.BOTH, "amount", upstream, downstream,
                    f"Amount differs by {_money(abs(difference))}: upstream ({up_sys}) "
                    f"{_money(upstream.amount)} vs downstream ({down_sys}) {_money(downstream.amount)}"
                    + (f" ({metrics['pct_difference']}% of the upstream amount)." if "pct_difference" in metrics else "."),
                    details={"metrics": metrics, "signed_difference": format(difference, "f"),
                             "tolerance": format(config.amount_tolerance, "f")},
                    source_value=format(upstream.amount, "f"),
                    target_value=format(downstream.amount, "f"),
                )
            )

    if upstream.maturity_date and downstream.maturity_date:
        days = (downstream.maturity_date - upstream.maturity_date).days
        if abs(days) > config.maturity_tolerance_days:
            findings.append(
                _finding(
                    "RULE-MAT-001", Side.BOTH, "maturity_date", upstream, downstream,
                    f"Maturity date differs by {abs(days)} days: upstream ({up_sys}) "
                    f"{upstream.maturity_date.isoformat()} vs downstream ({down_sys}) {downstream.maturity_date.isoformat()}.",
                    details={"metrics": {"days_difference": abs(days)}, "signed_days": days,
                             "tolerance_days": config.maturity_tolerance_days},
                    source_value=upstream.maturity_date.isoformat(),
                    target_value=downstream.maturity_date.isoformat(),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# 3. Mapping configuration
# ---------------------------------------------------------------------------


def check_mapping(upstream: LoanSnapshot, downstream: LoanSnapshot, index: MappingIndex) -> list[Finding]:
    version = downstream.mapping_version
    source_raw = upstream.product_code_raw
    target_raw = downstream.product_code_raw
    if not version or not source_raw or not target_raw:
        return []  # missing inputs are reported by RULE-REQ-001

    def make(rule_id: str, explanation: str, details: dict[str, Any]) -> Finding:
        return _finding(rule_id, Side.BOTH, "product_type", upstream, downstream, explanation,
                        details={"mapping_version": version, **details},
                        source_value=source_raw, target_value=target_raw)

    if not index.has_version(version):
        return [make("RULE-MAP-003",
                     f"The downstream record references mapping version '{version}', "
                     f"which does not exist in the mapping configuration.",
                     {"reason": "VERSION_NOT_FOUND"})]

    rule = index.lookup(version, source_raw)
    if rule is None:
        return [make("RULE-MAP-003",
                     f"Mapping version '{version}' has no product rule for the upstream value '{source_raw}'.",
                     {"reason": "NO_RULE_FOR_SOURCE_VALUE"})]

    findings: list[Finding] = []
    if rule.target_value.strip().upper() != target_raw.strip().upper():
        findings.append(make(
            "RULE-MAP-001",
            f"Mapping version '{version}' (rule {rule.rule_id}) maps '{source_raw}' to '{rule.target_value}', "
            f"but the downstream product code is '{target_raw}'.",
            {"mapping_rule_id": rule.rule_id, "expected_target_value": rule.target_value},
        ))

    status = index.version_status(version)
    if status != "ACTIVE":
        active = index.active_rule(rule.mapping_set, source_raw)
        if active is not None and active.target_value.strip().upper() != rule.target_value.strip().upper():
            findings.append(make(
                "RULE-MAP-002",
                f"The downstream record references mapping version '{version}' (status {status}), which maps "
                f"'{source_raw}' to '{rule.target_value}' (rule {rule.rule_id}). The active mapping "
                f"'{active.version}' maps it to '{active.target_value}' (rule {active.rule_id}).",
                {"recorded_rule_id": rule.rule_id, "recorded_version_status": status,
                 "active_version": active.version, "active_rule_id": active.rule_id,
                 "active_target_value": active.target_value},
            ))
    return findings


# ---------------------------------------------------------------------------
# 4. Booking status
# ---------------------------------------------------------------------------


def check_booking(
    upstream: LoanSnapshot | None, downstream: LoanSnapshot | None, config: ValidationConfig
) -> list[Finding]:
    if upstream is not None and downstream is None:
        if (upstream.status or "") in config.upstream_approved_statuses:
            return [_finding(
                "RULE-BOOK-002", Side.DOWNSTREAM, "booking_status", upstream, None,
                f"Upstream ({upstream.source_system}) status is {upstream.status}, "
                f"but no downstream record exists.",
                source_value=upstream.status, target_value=None,
            )]
        return []

    if downstream is not None and upstream is None:
        return [_finding(
            "RULE-BOOK-003", Side.UPSTREAM, "loan_id", None, downstream,
            f"Downstream ({downstream.source_system}) record exists with status {downstream.status}, "
            f"but no upstream record exists.",
            source_value=None, target_value=downstream.status,
        )]

    if downstream is not None and (downstream.status or "") in config.downstream_failed_statuses:
        error = downstream.booking_error or "no error message supplied"
        return [_finding(
            "RULE-BOOK-001", Side.DOWNSTREAM, "booking_status", upstream, downstream,
            f"Downstream ({downstream.source_system}) booking status is {downstream.status}: {error}.",
            details={"booking_error": downstream.booking_error},
            source_value=upstream.status if upstream else None, target_value=downstream.status,
        )]
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def evaluate_loan(
    upstream: LoanSnapshot | None,
    downstream: LoanSnapshot | None,
    index: MappingIndex,
    config: ValidationConfig,
) -> list[Finding]:
    """Run every rule for one loan. Pure: same inputs, same findings, same order."""
    findings: list[Finding] = []
    if upstream is not None:
        findings += check_required_and_types(Side.UPSTREAM, upstream, upstream, downstream)
    if downstream is not None:
        findings += check_required_and_types(Side.DOWNSTREAM, downstream, upstream, downstream)
    if upstream is not None and downstream is not None:
        findings += compare_records(upstream, downstream, config)
        findings += check_mapping(upstream, downstream, index)
    findings += check_booking(upstream, downstream, config)
    return findings
