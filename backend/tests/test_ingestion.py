"""Ingestion and versioning tests (in-memory database)."""

from sqlalchemy import select

from app.db.models import IngestionBatch, LoanRecord, RawSourceRecord
from app.integration.ingestion import ingest_payloads
from app.integration.vocab import SourceSystem

BASE = {
    "Name": "LN-5001",
    "LLC_BI__Product__c": "Term Loan",
    "LLC_BI__Amount__c": 1000000,
    "CurrencyIsoCode": "USD",
    "LLC_BI__Maturity_Date__c": "2029-01-31",
    "LLC_BI__Stage__c": "Approved",
    "LastModifiedDate": "2025-05-01T09:00:00Z",
}


def _versions(db, loan_id="LN-5001"):
    return db.scalars(
        select(LoanRecord).where(LoanRecord.loan_id == loan_id).order_by(LoanRecord.version)
    ).all()


def test_first_payload_creates_version_1(db):
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    assert (summary.received, summary.created) == (1, 1)
    [record] = _versions(db)
    assert record.version == 1 and record.is_current
    assert record.product_type == "TERM_LOAN"


def test_identical_payload_is_unchanged(db):
    ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    assert (summary.created, summary.unchanged) == (0, 1)
    assert len(_versions(db)) == 1


def test_changed_payload_creates_new_current_version(db):
    ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    changed = {**BASE, "LLC_BI__Amount__c": 1500000, "LastModifiedDate": "2025-06-01T09:00:00Z"}
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [changed])
    assert summary.created == 1

    v1, v2 = _versions(db)
    assert (v1.version, v1.is_current) == (1, False)
    assert (v2.version, v2.is_current) == (2, True)
    assert str(v2.amount) == "1500000"


def test_older_changed_payload_is_stale(db):
    ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    older = {**BASE, "LLC_BI__Stage__c": "Credit Review", "LastModifiedDate": "2025-04-01T09:00:00Z"}
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [older])
    assert (summary.created, summary.stale) == (0, 1)
    [current] = _versions(db)
    assert current.status == "APPROVED"


def test_two_versions_in_one_batch(db):
    first = {**BASE, "LLC_BI__Stage__c": "Credit Review", "LastModifiedDate": "2025-04-01T09:00:00Z"}
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [first, BASE])
    assert summary.created == 2
    assert [r.is_current for r in _versions(db)] == [False, True]


def test_rejected_payload_is_kept_for_audit(db):
    summary = ingest_payloads(db, SourceSystem.NCINO_SIM, [{"LLC_BI__Product__c": "Term Loan"}, "junk"])
    assert summary.rejected == 2
    assert db.scalars(select(LoanRecord)).all() == []

    raws = db.scalars(select(RawSourceRecord).order_by(RawSourceRecord.position)).all()
    assert [r.outcome for r in raws] == ["REJECTED", "REJECTED"]
    assert "Name" in raws[0].error
    assert raws[1].payload == "junk"


def test_normalization_issues_are_stored(db):
    bad = {**BASE, "LLC_BI__Amount__c": "1,OOO,000"}
    ingest_payloads(db, SourceSystem.NCINO_SIM, [bad])
    [record] = _versions(db)
    assert record.amount is None
    assert record.normalization_issues[0]["field"] == "amount"


def test_batch_counts_recorded(db):
    ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE, BASE, "junk"])
    batch = db.scalars(select(IngestionBatch)).one()
    assert (batch.received, batch.created, batch.unchanged, batch.rejected) == (3, 1, 1, 1)
    assert batch.completed_at is not None


def test_same_loan_id_in_each_source_is_versioned_independently(db):
    ingest_payloads(db, SourceSystem.NCINO_SIM, [BASE])
    ingest_payloads(
        db,
        SourceSystem.LOANIQ_SIM,
        [{"loanReference": "LN-5001", "productCode": "TERM", "globalAmount": 1000000, "currency": "USD"}],
    )
    records = _versions(db)
    assert sorted(r.source_system for r in records) == ["LOANIQ_SIM", "NCINO_SIM"]
    assert all(r.version == 1 and r.is_current for r in records)
