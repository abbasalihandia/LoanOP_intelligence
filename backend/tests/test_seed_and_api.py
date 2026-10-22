"""End-to-end Phase 1 checks: seed data loads and the API exposes it."""

from app.config import get_settings
from app.scripts.seed import run_seed


def _by_source(report):
    return {s.source_system.value: s for s in report.ingestion}


# --- Seeding ---------------------------------------------------------------


def test_seed_counts(seed_report):
    assert seed_report.reference_counts == {
        "mapping_rules": 8,
        "agreement_clauses": 8,
        "historical_exceptions": 5,
    }
    up = _by_source(seed_report)["NCINO_SIM"]
    down = _by_source(seed_report)["LOANIQ_SIM"]
    assert (up.received, up.created, up.unchanged, up.stale, up.rejected) == (13, 11, 1, 0, 1)
    assert (down.received, down.created, down.unchanged, down.stale, down.rejected) == (11, 9, 0, 0, 2)


def test_reseed_is_idempotent(db, seed_report):
    second = run_seed(db, get_settings().seed_data_dir, trigger="test")
    up = _by_source(second)["NCINO_SIM"]
    down = _by_source(second)["LOANIQ_SIM"]
    assert up.created == 0 and down.created == 0
    assert up.stale == 1  # the older LN-1001 'Credit Review' snapshot
    assert second.reference_counts["mapping_rules"] == 8


# --- Loans API -------------------------------------------------------------


def test_list_loans(client, seed_report):
    loans = client.get("/api/loans").json()
    assert [loan["loan_id"] for loan in loans] == [f"LN-{n}" for n in range(1001, 1011)]

    ln1008 = next(loan for loan in loans if loan["loan_id"] == "LN-1008")
    assert ln1008["upstream"] is not None
    assert ln1008["downstream"] is None  # never booked downstream


def test_ln1001_product_mismatch_scenario(client, seed_report):
    detail = client.get("/api/loans/LN-1001").json()
    assert detail["upstream"]["product_type"] == "REVOLVING_CREDIT"
    assert detail["upstream"]["version"] == 2
    assert [v["status"] for v in detail["upstream_history"]] == ["CREDIT_REVIEW", "APPROVED"]

    assert detail["downstream"]["product_type"] == "TERM_LOAN"
    assert detail["downstream"]["product_code_raw"] == "TERM"
    assert detail["downstream"]["mapping_version"] == "PRODMAP-v1"


def test_amount_serialized_without_precision_loss(client, seed_report):
    detail = client.get("/api/loans/LN-1003").json()
    assert detail["upstream"]["amount"] in ("25000000.0", "25000000.00", "25000000")
    assert detail["downstream"]["amount"] == "20000000"


def test_ln1009_amount_typo_surfaces_as_issue(client, seed_report):
    downstream = client.get("/api/loans/LN-1009").json()["downstream"]
    assert downstream["amount"] is None
    assert downstream["normalization_issues"][0]["raw_value"] == "12,5OO,000"


def test_loan_lookup_is_case_insensitive(client, seed_report):
    assert client.get("/api/loans/ln-1002").status_code == 200


def test_unknown_loan_returns_404(client, seed_report):
    assert client.get("/api/loans/LN-9999").status_code == 404


# --- Reference API ---------------------------------------------------------


def test_mapping_rules_filter_by_version(client, seed_report):
    rules = client.get("/api/reference/mapping-rules", params={"version": "PRODMAP-v1"}).json()
    assert len(rules) == 4
    revolving = next(r for r in rules if r["source_value"] == "Revolving Credit")
    assert revolving["target_value"] == "TERM"


def test_clauses_for_ln1003_include_amendment(client, seed_report):
    clauses = client.get("/api/reference/clauses", params={"loan_id": "LN-1003"}).json()
    assert {c["document_type"] for c in clauses} == {"FACILITY_AGREEMENT", "AMENDMENT"}


def test_ln1004_has_no_clauses(client, seed_report):
    assert client.get("/api/reference/clauses", params={"loan_id": "LN-1004"}).json() == []


def test_historical_exceptions_filter_by_category(client, seed_report):
    cases = client.get("/api/reference/historical-exceptions", params={"category": "PRODUCT_MISMATCH"}).json()
    assert {c["case_id"] for c in cases} == {"HX-2024-0117", "HX-2025-0090"}


# --- Simulated sources and ingestion API -----------------------------------


def test_mock_feeds_are_labelled_simulated(client):
    ncino = client.get("/api/mock/ncino/loans").json()
    loaniq = client.get("/api/mock/loaniq/loans").json()
    assert ncino["simulated"] is True and len(ncino["records"]) == 13
    assert loaniq["simulated"] is True and len(loaniq["records"]) == 11


def test_ingestion_run_via_api(client):
    first = client.post("/api/ingestion/run").json()
    assert [s["created"] for s in first] == [11, 9]

    second = client.post("/api/ingestion/run", params={"source": "LOANIQ_SIM"}).json()
    assert len(second) == 1 and second[0]["created"] == 0 and second[0]["unchanged"] == 9


def test_rejected_raw_records_visible(client, seed_report):
    rejected = client.get("/api/ingestion/raw-records", params={"outcome": "REJECTED"}).json()
    assert len(rejected) == 3
    assert all(r["error"] for r in rejected)


def test_batches_listed(client, seed_report):
    batches = client.get("/api/ingestion/batches").json()
    assert {b["source_system"] for b in batches} == {"NCINO_SIM", "LOANIQ_SIM"}
