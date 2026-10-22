"""Source-specific normalization into one canonical loan shape.

Design rule: normalization is lenient about *business content* and strict
only about *structure*.

  * A payload is REJECTED only if it is not a JSON object or has no loan
    identifier, because without an identifier it cannot be correlated.
  * Missing business fields stay None. Detecting them is the validation
    engine's job (Phase 2), not ingestion's.
  * Values that cannot be parsed (bad amount, bad date, unknown product)
    become None and are recorded as NormalizationIssues, so Phase 2 can
    raise data-type exceptions with the original raw value.

This module is pure Python (no database), so it is easy to unit test.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integration.vocab import (
    DOWNSTREAM,
    LOANIQ_PRODUCT_CODES,
    NCINO_PRODUCT_NAMES,
    UPSTREAM,
    ProductType,
    SourceSystem,
)


class IngestionRejected(Exception):
    """Raised when a payload is structurally unusable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class NormalizationIssue:
    field: str
    raw_value: Any
    issue: str

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "raw_value": self.raw_value, "issue": self.issue}


# Fields that define a record's content. source_updated_at is excluded on
# purpose: a re-sent record with a new timestamp but identical content is
# not a new version.
HASHED_FIELDS = (
    "source_system",
    "loan_id",
    "facility_id",
    "borrower_name",
    "product_type",
    "product_code_raw",
    "currency",
    "amount",
    "maturity_date",
    "status",
    "mapping_version",
    "booking_error",
)


@dataclass
class NormalizedLoan:
    source_system: SourceSystem
    loan_id: str
    facility_id: str | None = None
    borrower_name: str | None = None
    product_type: ProductType | None = None
    product_code_raw: str | None = None
    currency: str | None = None
    amount: Decimal | None = None
    maturity_date: date | None = None
    status: str | None = None
    mapping_version: str | None = None
    booking_error: str | None = None
    source_updated_at: datetime | None = None
    issues: list[NormalizationIssue] = field(default_factory=list)

    def content_hash(self) -> str:
        content: dict[str, Any] = {name: _hashable(getattr(self, name)) for name in HASHED_FIELDS}
        content["issues"] = [issue.to_dict() for issue in self.issues]
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _hashable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        # 10000000, 10000000.0 and 10000000.00 must hash identically.
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, SourceSystem | ProductType):
        return value.value
    return value


# ---------------------------------------------------------------------------
# Field parsers. Each appends to `issues` instead of raising.
# ---------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_DD_MON_YYYY = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value)
    return text or None


def _status_code(value: Any) -> str | None:
    """'Credit Review' -> 'CREDIT_REVIEW'."""
    text = _clean_str(value)
    if text is None:
        return None
    code = _NON_ALNUM.sub("_", text).strip("_").upper()
    return code or None


def _amount(value: Any, field_name: str, issues: list[NormalizationIssue]) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        issues.append(NormalizationIssue(field_name, value, "Expected a number, got a boolean"))
        return None
    if isinstance(value, int | float):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace(" ", "")
        if not text:
            return None
    else:
        issues.append(NormalizationIssue(field_name, value, "Expected a number or numeric string"))
        return None

    try:
        amount = Decimal(text)
    except InvalidOperation:
        issues.append(NormalizationIssue(field_name, value, "Not a valid decimal amount"))
        return None
    if not amount.is_finite():
        issues.append(NormalizationIssue(field_name, value, "Amount is not a finite number"))
        return None
    return amount


def _iso_date(text: str) -> date:
    return date.fromisoformat(text)


def _dd_mon_yyyy(text: str) -> date:
    """'30-Jun-2030' -> date(2030, 6, 30), independent of OS locale."""
    match = _DD_MON_YYYY.match(text)
    if not match:
        raise ValueError(text)
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.upper())
    if month is None:
        raise ValueError(text)
    return date(int(year), month, int(day))


def _date(
    value: Any,
    field_name: str,
    issues: list[NormalizationIssue],
    parsers: tuple[Callable[[str], date], ...],
    expected: str,
) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(NormalizationIssue(field_name, value, f"Expected a date string ({expected})"))
        return None
    text = value.strip()
    if not text:
        return None
    for parser in parsers:
        try:
            return parser(text)
        except ValueError:
            continue
    issues.append(NormalizationIssue(field_name, value, f"Unrecognized date (expected {expected})"))
    return None


def _timestamp(value: Any, field_name: str, issues: list[NormalizationIssue]) -> datetime | None:
    """ISO 8601 timestamp -> naive UTC. Naive input is assumed to be UTC."""
    text = _clean_str(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        issues.append(NormalizationIssue(field_name, value, "Not an ISO 8601 timestamp"))
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _currency(value: Any, field_name: str, issues: list[NormalizationIssue]) -> str | None:
    text = _clean_str(value)
    if text is None:
        return None
    code = text.upper()
    if len(code) == 3 and code.isascii() and code.isalpha():
        return code
    issues.append(NormalizationIssue(field_name, value, "Not a 3-letter currency code"))
    return None


def _product(
    value: Any,
    field_name: str,
    issues: list[NormalizationIssue],
    lookup: dict[str, ProductType],
    key: Callable[[str], str],
) -> tuple[ProductType | None, str | None]:
    raw = _clean_str(value)
    if raw is None:
        return None, None
    product = lookup.get(key(raw))
    if product is None:
        issues.append(NormalizationIssue(field_name, value, "Unrecognized product value"))
    return product, raw


def _require_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IngestionRejected("Payload is not a JSON object")
    return payload


def _loan_id(payload: dict[str, Any], key: str) -> str:
    loan_id = _clean_str(payload.get(key))
    if not loan_id:
        raise IngestionRejected(f"Missing loan identifier field '{key}'")
    return loan_id.upper()


# ---------------------------------------------------------------------------
# Source normalizers
# ---------------------------------------------------------------------------


def normalize_ncino(payload: Any) -> NormalizedLoan:
    """Simulated nCino loan payload -> canonical loan."""
    data = _require_object(payload)
    loan_id = _loan_id(data, "Name")
    issues: list[NormalizationIssue] = []

    product_type, product_raw = _product(
        data.get("LLC_BI__Product__c"), "product_type", issues, NCINO_PRODUCT_NAMES, str.lower
    )
    currency = _currency(data.get("CurrencyIsoCode"), "currency", issues)
    amount = _amount(data.get("LLC_BI__Amount__c"), "amount", issues)
    maturity = _date(
        data.get("LLC_BI__Maturity_Date__c"), "maturity_date", issues, (_iso_date,), "YYYY-MM-DD"
    )
    updated_at = _timestamp(data.get("LastModifiedDate"), "source_updated_at", issues)

    return NormalizedLoan(
        source_system=UPSTREAM,
        loan_id=loan_id,
        facility_id=_clean_str(data.get("Facility_Ref__c")),
        borrower_name=_clean_str(data.get("LLC_BI__Borrower_Name__c")),
        product_type=product_type,
        product_code_raw=product_raw,
        currency=currency,
        amount=amount,
        maturity_date=maturity,
        status=_status_code(data.get("LLC_BI__Stage__c")),
        source_updated_at=updated_at,
        issues=issues,
    )


def normalize_loaniq(payload: Any) -> NormalizedLoan:
    """Simulated Loan IQ outstanding payload -> canonical loan."""
    data = _require_object(payload)
    loan_id = _loan_id(data, "loanReference")
    issues: list[NormalizationIssue] = []

    product_type, product_raw = _product(
        data.get("productCode"), "product_type", issues, LOANIQ_PRODUCT_CODES, str.upper
    )
    currency = _currency(data.get("currency"), "currency", issues)
    amount = _amount(data.get("globalAmount"), "amount", issues)
    maturity = _date(
        data.get("expiryDate"),
        "maturity_date",
        issues,
        (_dd_mon_yyyy, _iso_date),
        "DD-Mon-YYYY or YYYY-MM-DD",
    )
    updated_at = _timestamp(data.get("lastUpdated"), "source_updated_at", issues)

    return NormalizedLoan(
        source_system=DOWNSTREAM,
        loan_id=loan_id,
        facility_id=_clean_str(data.get("facilityAlias")),
        borrower_name=_clean_str(data.get("borrowerShortName")),
        product_type=product_type,
        product_code_raw=product_raw,
        currency=currency,
        amount=amount,
        maturity_date=maturity,
        status=_status_code(data.get("bookingStatus")),
        mapping_version=_clean_str(data.get("mappingVersion")),
        booking_error=_clean_str(data.get("bookingError")),
        source_updated_at=updated_at,
        issues=issues,
    )


NORMALIZERS: dict[SourceSystem, Callable[[Any], NormalizedLoan]] = {
    SourceSystem.NCINO_SIM: normalize_ncino,
    SourceSystem.LOANIQ_SIM: normalize_loaniq,
}
