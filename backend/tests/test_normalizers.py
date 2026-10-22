"""Pure normalization tests (no database)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.integration.normalizers import IngestionRejected, normalize_loaniq, normalize_ncino
from app.integration.vocab import ProductType, SourceSystem

NCINO_LN1001 = {
    "Name": "LN-1001",
    "Facility_Ref__c": "FAC-1001",
    "LLC_BI__Borrower_Name__c": "Northwind Logistics Ltd",
    "LLC_BI__Product__c": "Revolving Credit",
    "LLC_BI__Amount__c": 10000000.00,
    "CurrencyIsoCode": "usd",
    "LLC_BI__Maturity_Date__c": "2030-06-30",
    "LLC_BI__Stage__c": "Credit Review",
    "LastModifiedDate": "2025-01-20T10:15:00Z",
}

LOANIQ_LN1001 = {
    "loanReference": "ln-1001",
    "facilityAlias": "FAC-1001",
    "productCode": "term",
    "globalAmount": 10000000,
    "currency": "USD",
    "expiryDate": "30-Jun-2030",
    "bookingStatus": "BOOKED",
    "mappingVersion": "PRODMAP-v1",
    "lastUpdated": "2025-02-10T14:15:00+05:30",
}


def test_ncino_payload_normalized():
    loan = normalize_ncino(NCINO_LN1001)
    assert loan.source_system is SourceSystem.NCINO_SIM
    assert loan.loan_id == "LN-1001"
    assert loan.product_type is ProductType.REVOLVING_CREDIT
    assert loan.product_code_raw == "Revolving Credit"
    assert loan.amount == Decimal("10000000")
    assert loan.currency == "USD"
    assert loan.maturity_date == date(2030, 6, 30)
    assert loan.status == "CREDIT_REVIEW"
    assert loan.issues == []


def test_loaniq_payload_normalized():
    loan = normalize_loaniq(LOANIQ_LN1001)
    assert loan.source_system is SourceSystem.LOANIQ_SIM
    assert loan.loan_id == "LN-1001"  # upper-cased for correlation
    assert loan.product_type is ProductType.TERM_LOAN
    assert loan.product_code_raw == "term"
    assert loan.maturity_date == date(2030, 6, 30)
    assert loan.mapping_version == "PRODMAP-v1"
    assert loan.issues == []


def test_offset_timestamp_converted_to_naive_utc():
    loan = normalize_loaniq(LOANIQ_LN1001)
    assert loan.source_updated_at == datetime(2025, 2, 10, 8, 45)
    assert loan.source_updated_at.tzinfo is None


def test_unparseable_amount_becomes_issue_not_rejection():
    loan = normalize_loaniq({**LOANIQ_LN1001, "globalAmount": "12,5OO,000"})
    assert loan.amount is None
    assert [(i.field, i.raw_value) for i in loan.issues] == [("amount", "12,5OO,000")]


def test_comma_formatted_amount_accepted():
    loan = normalize_loaniq({**LOANIQ_LN1001, "globalAmount": "12,500,000.00"})
    assert loan.amount == Decimal("12500000")
    assert loan.issues == []


def test_unknown_product_recorded_as_issue():
    loan = normalize_loaniq({**LOANIQ_LN1001, "productCode": "MYSTERY"})
    assert loan.product_type is None
    assert loan.product_code_raw == "MYSTERY"
    assert loan.issues[0].field == "product_type"


def test_bad_date_and_currency_recorded_as_issues():
    loan = normalize_ncino({**NCINO_LN1001, "LLC_BI__Maturity_Date__c": "31/12/2029", "CurrencyIsoCode": "US$"})
    assert loan.maturity_date is None
    assert loan.currency is None
    assert {i.field for i in loan.issues} == {"maturity_date", "currency"}


def test_missing_business_field_is_none_without_issue():
    loan = normalize_ncino({**NCINO_LN1001, "LLC_BI__Maturity_Date__c": None})
    assert loan.maturity_date is None
    assert loan.issues == []  # required-field checks belong to Phase 2


@pytest.mark.parametrize(
    "normalizer, payload, reason_fragment",
    [
        (normalize_ncino, {"LLC_BI__Product__c": "Term Loan"}, "'Name'"),
        (normalize_loaniq, {"productCode": "TERM"}, "'loanReference'"),
        (normalize_ncino, {"Name": "   "}, "'Name'"),
        (normalize_loaniq, "not an object", "not a JSON object"),
        (normalize_ncino, ["LN-1001"], "not a JSON object"),
    ],
)
def test_structurally_unusable_payloads_rejected(normalizer, payload, reason_fragment):
    with pytest.raises(IngestionRejected) as exc_info:
        normalizer(payload)
    assert reason_fragment in exc_info.value.reason


def test_hash_ignores_source_timestamp_and_amount_formatting():
    a = normalize_ncino(NCINO_LN1001)
    b = normalize_ncino({**NCINO_LN1001, "LastModifiedDate": "2025-03-01T00:00:00Z", "LLC_BI__Amount__c": "10,000,000"})
    assert a.content_hash() == b.content_hash()


def test_hash_changes_when_content_changes():
    a = normalize_ncino(NCINO_LN1001)
    b = normalize_ncino({**NCINO_LN1001, "LLC_BI__Stage__c": "Approved"})
    assert a.content_hash() != b.content_hash()
