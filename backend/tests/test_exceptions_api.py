"""Phase 2 end-to-end: validation over seed data, exception lifecycle, API."""

import pytest

from app.integration.ingestion import ingest_payloads
from app.integration.vocab import SourceSystem
from app.validation.config import get_validation_config
from app.validation.runner import run_validation

EXPECTED = [
    ("EXC-00001", "LN-1001", "RULE-PRODUCT-001", "HIGH"),
    ("EXC-00002", "LN-1001", "RULE-MAP-002", "MEDIUM"),
    ("EXC-00003", "LN-1003", "RULE-AMT-001", "CRITICAL"),
    ("EXC-00004", "LN-1004", "RULE-CCY-001", "CRITICAL"),
    ("EXC-00005", "LN-1005", "RULE-MAT-001", "HIGH"),
    ("EXC-00006", "LN-1006", "RULE-REQ-001", "HIGH"),
    ("EXC-00007", "LN-1007", "RULE-BOOK-001", "HIGH"),
    ("EXC-00008", "LN-1008", "RULE-BOOK-002", "MEDIUM"),
    ("EXC-00009", "LN-1009", "RULE-TYPE-001", "HIGH"),
    ("EXC-00010", "LN-1010", "RULE-PRODUCT-001", "HIGH"),
    ("EXC-00011", "LN-1010", "RULE-MAP-001", "HIGH"),
]


@pytest.fixture
def validated(db, seed_report):
    return run_validation(db, get_validation_config())


def _patch(client, exception_id, to_status, actor="analyst.test", reason=None):
    body = {"to_status": to_status, "actor": actor}
    if reason is not None:
        body["reason"] = reason
    return client.patch(f"/api/exceptions/{exception_id}/status", json=body)


# --- Validation over the seed scenarios ------------------------------------


def test_seed_scenarios_produce_expected_exceptions(client, validated):
    assert (validated.loans_evaluated, validated.findings, validated.created) == (10, 11, 11)
    rows = client.get("/api/exceptions").json()
    assert [(r["exception_id"], r["loan_id"], r["rule_id"], r["severity"]) for r in rows] == EXPECTED
    assert all(r["status"] == "OPEN" and r["still_detected"] for r in rows)


def test_control_loan_ln1002_has_no_exceptions(client, validated):
    assert client.get("/api/exceptions", params={"loan_id": "LN-1002"}).json() == []


def test_rerun_redetects_without_duplicating(db, client, validated):
    second = run_validation(db, get_validation_config())
    assert (second.created, second.redetected, second.suppressed) == (0, 11, 0)
    assert len(client.get("/api/exceptions").json()) == 11
    assert client.get("/api/exceptions/EXC-00001").json()["detection_count"] == 2


def test_validation_run_via_api(client, seed_report):
    run = client.post("/api/validation/run").json()
    assert run["created"] == 11
    assert len(run["config_fingerprint"]) == 64
    assert len(client.get("/api/validation/runs").json()) == 1


def test_rule_catalogue(client):
    rules = {r["rule_id"]: r for r in client.get("/api/validation/rules").json()}
    assert len(rules) == 12
    assert rules["RULE-AMT-001"]["severity_overrides"] == [
        {"metric": "pct_difference", "gte": "10", "severity": "CRITICAL"}
    ]


# --- Exception detail ------------------------------------------------------


def test_detail_includes_evaluated_records_and_history(client, validated):
    detail = client.get("/api/exceptions/exc-00002").json()  # case-insensitive
    assert detail["rule_id"] == "RULE-MAP-002"
    assert detail["upstream_record"]["product_type"] == "REVOLVING_CREDIT"
    assert detail["downstream_record"]["mapping_version"] == "PRODMAP-v1"
    assert detail["details"]["active_target_value"] == "REVOLVER"
    [created] = detail["status_history"]
    assert (created["from_status"], created["to_status"], created["actor"]) == (None, "OPEN", "system:validation")
    assert detail["allowed_next_statuses"] == ["UNDER_INVESTIGATION", "REJECTED", "ESCALATED"]


def test_ln1008_detail_has_no_downstream_record(client, validated):
    detail = client.get("/api/exceptions/EXC-00008").json()
    assert detail["downstream_record"] is None
    assert detail["upstream_record"]["loan_id"] == "LN-1008"


def test_unknown_exception_404(client, validated):
    assert client.get("/api/exceptions/EXC-99999").status_code == 404
    assert _patch(client, "EXC-99999", "UNDER_INVESTIGATION").status_code == 404


def test_summary(client, validated):
    summary = client.get("/api/exceptions/summary").json()
    assert (summary["total"], summary["active"]) == (11, 11)
    assert summary["by_severity"] == {"HIGH": 7, "MEDIUM": 2, "CRITICAL": 2}
    assert summary["by_status"] == {"OPEN": 11}


# --- Status changes --------------------------------------------------------


def test_analyst_status_change_recorded(client, validated):
    response = _patch(client, "EXC-00001", "UNDER_INVESTIGATION", actor="analyst.jdoe")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNDER_INVESTIGATION"
    assert [(h["to_status"], h["actor"]) for h in body["status_history"]] == [
        ("OPEN", "system:validation"),
        ("UNDER_INVESTIGATION", "analyst.jdoe"),
    ]


@pytest.mark.parametrize(
    "to_status, reason, expected_code",
    [
        ("RESOLVED", None, 409),  # not reachable from OPEN, and reserved for Phase 6
        ("RECOMMENDATION_GENERATED", None, 409),  # AI service only
        ("REJECTED", None, 409),  # reason required
        ("NOT_A_STATUS", None, 422),  # schema validation
    ],
)
def test_forbidden_status_changes(client, validated, to_status, reason, expected_code):
    assert _patch(client, "EXC-00001", to_status, reason=reason).status_code == expected_code
    assert client.get("/api/exceptions/EXC-00001").json()["status"] == "OPEN"


def test_system_actor_reserved(client, validated):
    response = _patch(client, "EXC-00001", "UNDER_INVESTIGATION", actor="system:me")
    assert response.status_code == 422


def test_resolved_not_settable_even_from_investigation(client, validated):
    _patch(client, "EXC-00001", "UNDER_INVESTIGATION")
    response = _patch(client, "EXC-00001", "RESOLVED")
    assert response.status_code == 409
    assert "resolution workflow" in response.json()["detail"]


# --- Lifecycle across runs -------------------------------------------------


def test_rejected_exception_is_suppressed_on_rerun(db, client, validated):
    assert _patch(client, "EXC-00002", "REJECTED", reason="Known retired-mapping artefact").status_code == 200
    rerun = run_validation(db, get_validation_config())
    assert (rerun.created, rerun.suppressed, rerun.redetected) == (0, 1, 10)


def test_closed_exception_recurs_when_values_change(db, client, validated):
    _patch(client, "EXC-00003", "REJECTED", reason="Amendment confirmed; upstream to be corrected")

    ingest_payloads(db, SourceSystem.LOANIQ_SIM, [{
        "loanReference": "LN-1003", "facilityAlias": "FAC-1003", "borrowerShortName": "COBALT RIDGE MINING",
        "productCode": "TERM", "globalAmount": 22000000, "currency": "USD", "expiryDate": "31-Mar-2031",
        "bookingStatus": "BOOKED", "mappingVersion": "PRODMAP-v1", "lastUpdated": "2025-10-01T09:00:00Z",
    }], trigger="test")

    rerun = run_validation(db, get_validation_config())
    assert rerun.created == 1
    new = client.get("/api/exceptions", params={"loan_id": "LN-1003", "active_only": True}).json()
    assert [(e["exception_id"], e["target_value"]) for e in new] == [("EXC-00012", "22000000")]
    history = client.get("/api/exceptions/EXC-00012").json()["status_history"]
    assert "recurrence of EXC-00003" in history[0]["reason"]


def test_fixed_data_flags_exception_but_does_not_close_it(db, client, validated):
    ingest_payloads(db, SourceSystem.LOANIQ_SIM, [{
        "loanReference": "LN-1005", "facilityAlias": "FAC-1005", "borrowerShortName": "SILVERLINE TELECOM",
        "productCode": "TERM", "globalAmount": 7500000, "currency": "USD", "expiryDate": "31-Dec-2029",
        "bookingStatus": "BOOKED", "mappingVersion": "PRODMAP-v2", "lastUpdated": "2025-10-01T09:00:00Z",
    }], trigger="test")

    rerun = run_validation(db, get_validation_config())
    assert rerun.no_longer_detected == 1
    detail = client.get("/api/exceptions/EXC-00005").json()
    assert detail["status"] == "OPEN"  # closing is an analyst decision
    assert detail["still_detected"] is False
    assert client.get("/api/exceptions/summary").json()["active_no_longer_detected"] == 1
