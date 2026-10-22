"""Inputs and outputs of the validation engine."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    """Which record(s) a finding concerns."""

    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"
    BOTH = "BOTH"


@dataclass(frozen=True)
class LoanSnapshot:
    """The current normalized record for one loan in one source system."""

    loan_id: str
    source_system: str
    record_id: int | None = None
    version: int | None = None
    facility_id: str | None = None
    product_type: str | None = None
    product_code_raw: str | None = None
    currency: str | None = None
    amount: Decimal | None = None
    maturity_date: date | None = None
    status: str | None = None
    mapping_version: str | None = None
    booking_error: str | None = None
    normalization_issues: tuple[dict[str, Any], ...] = ()

    def issue_for(self, field_name: str) -> dict[str, Any] | None:
        return next((i for i in self.normalization_issues if i.get("field") == field_name), None)


@dataclass(frozen=True)
class MappingRuleView:
    """The subset of a mapping rule the engine needs."""

    rule_id: str
    mapping_set: str
    version: str
    source_value: str
    target_value: str
    status: str


@dataclass
class Finding:
    """One failed rule for one loan. Becomes (or updates) an exception record."""

    loan_id: str
    rule_id: str
    category: str
    side: Side
    field_name: str | None
    source_value: str | None
    target_value: str | None
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)
    upstream_record_id: int | None = None
    downstream_record_id: int | None = None
    severity: str | None = None

    @property
    def fingerprint(self) -> str:
        """Identifies 'the same problem' across validation runs."""
        return f"{self.loan_id}|{self.rule_id}|{self.field_name or '-'}|{self.side.value}"

    @property
    def value_signature(self) -> str:
        """Identifies 'the same values' — used to decide whether a closed case recurred."""
        encoded = json.dumps([self.source_value, self.target_value], separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
