"""Phase 6: analyst resolution, AI/human separation, feedback into history, recurrence, audit."""

import pytest

from app.api.ai import get_llm_client, get_max_attempts
from app.integration.ingestion import ingest_payloads
from app.integration.vocab import SourceSystem
from app.main import app
from app.validation.config import get_validation_config
from app.validation.runner import run_validation
from tests.ai_helpers import FakeLlm, as_json, cause, check, ids_of, report

AI_CAUSE_TEXT = "The downstream product was derived from the retired mapping PRODMAP-v1."


@pytest.fixture
def ready(db, seed_report):
    run_validation(db, get_validation_config())


@pytest.fixture
def fake_llm():
    def install(fake: FakeLlm) -> FakeLlm:
        app.dependency_overrides[get_llm_client] = lambda: fake
        app.dependency_overrides[get_max_attempts] = lambda: 1
        return fake

    yield install
    app.dependency_overrides.clear()


def _items(client, exception_id):
    return client.get(f"/api/exceptions/{exception_id}/evidence").json()["items"]


def _start(client, exception_id):
    r = client.patch(f"/api/exceptions/{exception_id}/status",
                     json={"to_status": "UNDER_INVESTIGATION", "actor": "analyst.test"})
    assert r.status_code == 200, r.text


def _payload(**overrides):
    data = {
        "resolved_by": "analyst.merajul",
        "analyst_decision": "NO_AI_REPORT",
        "root_cause_category": "MANUAL_KEYING_ERROR",
        "confirmed_root_cause": "Maturity day keyed as 01 instead of 31 at booking.",
        "record_in_error": "DOWNSTREAM",
        "final_action": "Servicing corrected the maturity date in Loan IQ.",
        "outcome": "CORRECTED_IN_SOURCE",
        "evidence_ids": [],
    }
    data.update(overrides)
    return data


def _resolve(client, exception_id, **overrides):
    return client.post(f"/api/exceptions/{exception_id}/resolution", json=_payload(**overrides))


def _ln1005_ready(client):
    clause = ids_of(_items(client, "EXC-00005"), "AGREEMENT_CLAUSE")[0]
    _start(client, "EXC-00005")
    return clause


def _investigate_ln1001(client, fake_llm):
    items = _items(client, "EXC-00001")
    v1 = ids_of(items, "MAPPING_RULE", "V1-001")[0]
    clause = ids_of(items, "AGREEMENT_CLAUSE")[0]
    fake_llm(FakeLlm(as_json(report(
        "EXC-00001",
        probable_causes=[cause(AI_CAUSE_TEXT, [v1, clause]),
                         cause("Manual override at booking.", [], claim_type="UNVERIFIED_POSSIBILITY", confidence="low")],
        recommended_checks=[check("Verify the mapping version used at booking.", [v1])],
    ))))
    body = client.post("/api/exceptions/EXC-00001/investigations", json={"requested_by": "analyst.test"}).json()
    assert body["status"] == "SUCCEEDED"
    return body["investigation_id"], v1, clause


# --- Resolution without AI -------------------------------------------------------


def test_resolve_without_ai(client, ready):
    clause = _ln1005_ready(client)
    response = _resolve(client, "EXC-00005", evidence_ids=[clause])
    assert response.status_code == 201, response.text
    res = response.json()
    assert (res["resolution_id"], res["analyst_decision"], res["ai_recommendation"]) == ("RES-00001", "NO_AI_REPORT", None)
    assert res["historical_case_id"] == "HX-RES-00001"

    detail = client.get("/api/exceptions/EXC-00005").json()
    assert detail["status"] == "RESOLVED" and detail["can_resolve"] is False
    last = detail["status_history"][-1]
    assert (last["to_status"], last["actor"]) == ("RESOLVED", "analyst.merajul")

    # Loan records are untouched by resolving.
    assert client.get("/api/loans/LN-1005").json()["downstream"]["maturity_date"] == "2029-12-01"


def test_cannot_resolve_from_open(client, ready):
    clause = ids_of(_items(client, "EXC-00005"), "AGREEMENT_CLAUSE")[0]
    response = _resolve(client, "EXC-00005", evidence_ids=[clause])
    assert response.status_code == 409
    assert "UNDER_INVESTIGATION" in response.json()["detail"]


def test_cannot_resolve_twice(client, ready):
    clause = _ln1005_ready(client)
    assert _resolve(client, "EXC-00005", evidence_ids=[clause]).status_code == 201
    assert _resolve(client, "EXC-00005", evidence_ids=[clause]).status_code == 409


def test_status_endpoint_still_cannot_set_resolved(client, ready):
    _start(client, "EXC-00005")
    response = client.patch("/api/exceptions/EXC-00005/status", json={"to_status": "RESOLVED", "actor": "analyst.test"})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"evidence_ids": ["EV-99999"]}, "not part of this exception's evidence"),
        ({"record_in_error": "NEITHER"}, "CORRECTED_IN_SOURCE requires"),
        ({"outcome": "NO_CHANGE_REQUIRED"}, "set record_in_error to NEITHER"),
        ({"resolved_by": "system:bot"}, "human reviewer"),
        ({"confirmed_root_cause": "typo"}, "at least 10 characters"),
        ({"analyst_decision": "AI_ACCEPTED"}, "requires ai_investigation_id"),
        ({"ai_investigation_id": "AI-00001"}, "must not reference an AI investigation"),
    ],
)
def test_invalid_resolutions_rejected(client, ready, overrides, fragment):
    clause = _ln1005_ready(client)
    payload = {"evidence_ids": [clause], **overrides}
    response = _resolve(client, "EXC-00005", **payload)
    assert response.status_code == 422, response.text
    assert fragment in response.json()["detail"]
    assert client.get("/api/exceptions/EXC-00005").json()["status"] == "UNDER_INVESTIGATION"


def test_schema_rejects_unknown_category(client, ready):
    clause = _ln1005_ready(client)
    assert _resolve(client, "EXC-00005", evidence_ids=[clause], root_cause_category="GUESS").status_code == 422


# --- Resolution after AI: separation of AI recommendation and analyst decision -----------


def test_ai_accepted_keeps_ai_and_analyst_separate(client, ready, fake_llm):
    investigation_id, v1, clause = _investigate_ln1001(client, fake_llm)
    response = _resolve(
        client, "EXC-00001",
        analyst_decision="AI_ACCEPTED", ai_investigation_id=investigation_id, ai_cause_index=0,
        root_cause_category="OUTDATED_MAPPING_APPLIED",
        confirmed_root_cause="Booked on 2025-02-10 under PRODMAP-v1, whose Revolving Credit rule was defective; "
                             "never remediated after PRODMAP-v2.",
        final_action="Servicing changed the Loan IQ product to REVOLVER under ticket SIM-123.",
        evidence_ids=[v1, clause],
    )
    assert response.status_code == 201, response.text
    res = response.json()
    assert res["ai_investigation_id"] == investigation_id
    snapshot = res["ai_recommendation"]
    assert snapshot["label"] == "AI-generated recommendation (not confirmed)"
    assert snapshot["probable_causes"][0]["cause"] == AI_CAUSE_TEXT
    assert res["confirmed_root_cause"] != AI_CAUSE_TEXT

    # Only analyst text feeds history; AI text never does.
    cases = client.get("/api/reference/historical-exceptions", params={"loan_id": "LN-1001"}).json()
    [case] = [c for c in cases if c["origin"] == "ANALYST_CONFIRMED"]
    assert case["confirmed_root_cause"].startswith("[OUTDATED_MAPPING_APPLIED] Booked on 2025-02-10")
    assert AI_CAUSE_TEXT not in case["confirmed_root_cause"]


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"analyst_decision": "AI_ACCEPTED", "ai_cause_index": 5}, "requires ai_cause_index"),
        ({"analyst_decision": "AI_MODIFIED"}, "requires ai_cause_index"),
        ({"analyst_decision": "AI_REJECTED", "ai_cause_index": 0}, "must not select an AI cause"),
    ],
)
def test_ai_decision_consistency(client, ready, fake_llm, overrides, fragment):
    investigation_id, v1, _ = _investigate_ln1001(client, fake_llm)
    response = _resolve(client, "EXC-00001", ai_investigation_id=investigation_id, evidence_ids=[v1], **overrides)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_ai_report_of_another_exception_rejected(client, ready, fake_llm):
    investigation_id, _, _ = _investigate_ln1001(client, fake_llm)
    clause = _ln1005_ready(client)
    response = _resolve(client, "EXC-00005", analyst_decision="AI_REJECTED",
                        ai_investigation_id=investigation_id, evidence_ids=[clause])
    assert response.status_code == 422
    assert "does not belong to EXC-00005" in response.json()["detail"]


def test_ai_rejected_is_recorded(client, ready, fake_llm):
    investigation_id, v1, _ = _investigate_ln1001(client, fake_llm)
    res = _resolve(client, "EXC-00001", analyst_decision="AI_REJECTED", ai_investigation_id=investigation_id,
                   root_cause_category="OTHER", confirmed_root_cause="Product deliberately overridden by credit.",
                   record_in_error="UNDETERMINED", outcome="REFERRED_TO_OWNER",
                   final_action="Referred to the credit team.", evidence_ids=[v1]).json()
    assert res["analyst_decision"] == "AI_REJECTED" and res["ai_cause_index"] is None
    listed = client.get("/api/resolutions", params={"analyst_decision": "AI_REJECTED"}).json()
    assert [r["resolution_id"] for r in listed] == [res["resolution_id"]]


# --- Feedback into future investigations ----------------------------------------------


def test_confirmed_resolution_is_retrieved_for_similar_exception_on_another_loan(client, ready, fake_llm):
    investigation_id, v1, clause = _investigate_ln1001(client, fake_llm)
    _resolve(client, "EXC-00001", analyst_decision="AI_MODIFIED", ai_investigation_id=investigation_id, ai_cause_index=0,
             root_cause_category="OUTDATED_MAPPING_APPLIED",
             confirmed_root_cause="Retired PRODMAP-v1 rule applied at booking.",
             final_action="Loan IQ product corrected.", evidence_ids=[v1, clause])

    history = [i for i in _items(client, "EXC-00010") if i["evidence_type"] == "HISTORICAL_CASE"]
    confirmed = [i for i in history if i["content"]["origin"] == "ANALYST_CONFIRMED"]
    assert [i["content"]["case_id"] for i in confirmed] == ["HX-RES-00001"]
    assert "Not proof of the current cause" in confirmed[0]["relevance"]


# --- Recurrence after resolution -------------------------------------------------------


def _ln1005_downstream(borrower: str, updated: str) -> dict:
    return {
        "loanReference": "LN-1005", "facilityAlias": "FAC-1005", "borrowerShortName": borrower,
        "productCode": "TERM", "globalAmount": 7500000, "currency": "USD", "expiryDate": "01-Dec-2029",
        "bookingStatus": "BOOKED", "mappingVersion": "PRODMAP-v2", "lastUpdated": updated,
    }


def test_corrected_in_source_resurfaces_only_when_newer_data_still_wrong(db, client, ready):
    clause = _ln1005_ready(client)
    _resolve(client, "EXC-00005", evidence_ids=[clause])

    # No new data yet: awaiting the corrected feed, so suppressed.
    rerun = run_validation(db, get_validation_config())
    assert (rerun.created, rerun.suppressed) == (0, 1)

    # A newer downstream version arrives, but the maturity is still wrong.
    ingest_payloads(db, SourceSystem.LOANIQ_SIM, [_ln1005_downstream("SILVERLINE TELECOM INC", "2025-10-01T09:00:00Z")])
    rerun = run_validation(db, get_validation_config())
    assert rerun.created == 1
    [new] = client.get("/api/exceptions", params={"loan_id": "LN-1005", "active_only": True}).json()
    reason = client.get(f"/api/exceptions/{new['exception_id']}").json()["status_history"][0]["reason"]
    assert "newer record versions still show the same discrepancy" in reason


def test_no_change_required_stays_suppressed(db, client, ready):
    up = ids_of(_items(client, "EXC-00004"), "UPSTREAM_RECORD")[0]
    _start(client, "EXC-00004")
    assert _resolve(client, "EXC-00004", root_cause_category="LEGITIMATE_DIFFERENCE",
                    confirmed_root_cause="Facility is multi-currency; USD drawing is permitted.",
                    record_in_error="NEITHER", outcome="NO_CHANGE_REQUIRED",
                    final_action="No action; documented.", evidence_ids=[up]).status_code == 201

    ingest_payloads(db, SourceSystem.LOANIQ_SIM, [{
        "loanReference": "LN-1004", "facilityAlias": "FAC-1004", "borrowerShortName": "ALTAMIRA FOODS SA",
        "productCode": "REVOLVER", "globalAmount": 15000000, "currency": "USD", "expiryDate": "30-Jun-2029",
        "bookingStatus": "BOOKED", "mappingVersion": "PRODMAP-v2", "lastUpdated": "2025-10-01T09:00:00Z",
    }])
    rerun = run_validation(db, get_validation_config())
    assert rerun.created == 0
    assert client.get("/api/exceptions", params={"loan_id": "LN-1004", "active_only": True}).json() == []


# --- Audit trail ----------------------------------------------------------------------------


def test_audit_trail_distinguishes_ai_from_humans(client, ready, fake_llm):
    investigation_id, v1, clause = _investigate_ln1001(client, fake_llm)
    _resolve(client, "EXC-00001", analyst_decision="AI_ACCEPTED", ai_investigation_id=investigation_id, ai_cause_index=0,
             root_cause_category="OUTDATED_MAPPING_APPLIED", confirmed_root_cause="Retired PRODMAP-v1 rule applied.",
             final_action="Loan IQ product corrected.", evidence_ids=[v1])

    events = client.get("/api/exceptions/EXC-00001/audit").json()
    types = [(e["event_type"], e["actor_type"]) for e in events]
    expected_order = [
        ("EXCEPTION_CREATED", "SYSTEM"),
        ("AI_INVESTIGATION_REQUESTED", "ANALYST"),
        ("AI_INVESTIGATION_SUCCEEDED", "AI"),
        ("STATUS_CHANGED", "AI_SERVICE"),
        ("RESOLUTION_RECORDED", "ANALYST"),
    ]
    positions = [types.index(t) for t in expected_order]
    assert positions == sorted(positions)
    assert types[-1] == ("STATUS_CHANGED", "ANALYST")  # → RESOLVED by the reviewer
    ai_event = next(e for e in events if e["event_type"] == "AI_INVESTIGATION_SUCCEEDED")
    assert "Not a confirmed finding" in ai_event["summary"] and ai_event["reference"] == investigation_id
    assert ("EVIDENCE_RETRIEVED", "SYSTEM") in types


def test_resolution_options(client):
    options = client.get("/api/resolution/options").json()
    assert set(options) == {"analyst_decision", "root_cause_category", "record_in_error", "outcome"}
    assert {"value": "NO_AI_REPORT", "label": "Resolved without an AI report"} in options["analyst_decision"]


def test_resolution_404s(client, ready):
    assert client.get("/api/exceptions/EXC-00001/resolution").status_code == 404
    assert client.get("/api/exceptions/EXC-99999/audit").status_code == 404
