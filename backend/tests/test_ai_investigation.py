"""Phase 4: AI investigation through the real API and database, with a scripted fake LLM.

Covers the seven required situations:
  1. mapping rule clearly supports a probable cause        (LN-1001)
  2. mapping rule does not explain the discrepancy         (LN-1010)
  3. two sources of evidence conflict                      (LN-1003)
  4. required contractual evidence is missing              (LN-1004)
  5. model cites an evidence id that was not supplied
  6. Ollama unavailable
  7. invalid structured output
plus timeout, bounded retry, history-only causes, closed exceptions and audit.
"""

import pytest

from app.ai.errors import LlmModelNotFound, LlmTimeout, LlmUnavailable
from app.ai.schema import HYPOTHESIS_STATEMENT, INSUFFICIENT_STATEMENT
from app.api.ai import get_llm_client, get_max_attempts
from app.main import app
from app.validation.config import get_validation_config
from app.validation.runner import run_validation
from tests.ai_helpers import FakeLlm, as_json, cause, check, fact, ids_of, report


@pytest.fixture
def exceptions_ready(db, seed_report):
    run_validation(db, get_validation_config())


@pytest.fixture
def use_llm():
    """Install a FakeLlm for the API; returns a setter."""
    def install(fake: FakeLlm, max_attempts: int = 2) -> FakeLlm:
        app.dependency_overrides[get_llm_client] = lambda: fake
        app.dependency_overrides[get_max_attempts] = lambda: max_attempts
        return fake

    yield install
    app.dependency_overrides.clear()


def _items(client, exception_id):
    return client.get(f"/api/exceptions/{exception_id}/evidence").json()["items"]


def _investigate(client, exception_id, by="analyst.test"):
    return client.post(f"/api/exceptions/{exception_id}/investigations", json={"requested_by": by})


def _status(client, exception_id):
    return client.get(f"/api/exceptions/{exception_id}").json()["status"]


# --- 1. Mapping rule supports a probable cause ---------------------------------


def test_1_mapping_supports_probable_cause(client, exceptions_ready, use_llm):
    items = _items(client, "EXC-00001")
    up, down = ids_of(items, "UPSTREAM_RECORD")[0], ids_of(items, "DOWNSTREAM_RECORD")[0]
    v1, v2 = ids_of(items, "MAPPING_RULE", "V1-001")[0], ids_of(items, "MAPPING_RULE", "V2-001")[0]
    clause = ids_of(items, "AGREEMENT_CLAUSE")[0]
    history = ids_of(items, "HISTORICAL_CASE", "HX-2024-0117")[0]

    fake = use_llm(FakeLlm(as_json(report(
        "EXC-00001",
        summary="Upstream shows Revolving Credit; downstream shows TERM, booked under PRODMAP-v1.",
        confirmed_facts=[
            fact("The downstream record references mapping version PRODMAP-v1.", [down]),
            fact("PRODMAP-v1 maps Revolving Credit to TERM; the active PRODMAP-v2 maps it to REVOLVER.", [v1, v2]),
            fact("Clause 2.1 describes a revolving credit facility.", [clause]),
        ],
        probable_causes=[cause("The downstream product was derived from the retired mapping PRODMAP-v1.",
                               [v1, v2, down, clause])],
        alternative_explanations=[{"explanation": "Manual product selection at booking.",
                                   "supporting_evidence_ids": [],
                                   "why_less_likely": "The booked code matches the recorded mapping exactly."}],
        recommended_checks=[
            check("Verify the mapping version used when LN-1001 was booked.", [down, v1]),
            check("Confirm the intended product against the approved facility terms.", [clause, up]),
        ],
        uncertainties=["Whether the booking used PRODMAP-v1 automatically or by manual selection."],
        overall_assessment=f"An outdated mapping is a plausible cause; see also the similar case {history}.",
    ))))

    response = _investigate(client, "EXC-00001", by="analyst.merajul")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["investigation_id"] == "AI-00001"
    assert (body["status"], body["attempts"], body["model"]) == ("SUCCEEDED", 1, "fake-model")

    rep = body["report"]
    assert rep["report_type"] == "AI_GENERATED_RECOMMENDATION"
    assert rep["root_cause_statement"] == HYPOTHESIS_STATEMENT
    assert "not calibrated probabilities" in rep["confidence_note"]
    assert rep["observed_discrepancies"] == [{
        "field": "product_type", "upstream_value": "Revolving Credit", "downstream_value": "TERM",
        "validation_rule_id": "RULE-PRODUCT-001",
        "explanation": rep["observed_discrepancies"][0]["explanation"], "source": "DETERMINISTIC_VALIDATION",
    }]
    assert set(rep["evidence_package_ids"]) == {i["evidence_id"] for i in items}
    assert rep["policy_flags"] == []

    detail = client.get("/api/exceptions/EXC-00001").json()
    assert detail["status"] == "RECOMMENDATION_GENERATED"
    assert [(h["to_status"], h["actor"]) for h in detail["status_history"][1:]] == [
        ("UNDER_INVESTIGATION", "system:ai-investigation"),
        ("RECOMMENDATION_GENERATED", "system:ai-investigation"),
    ]
    assert "requested by analyst.merajul" in detail["status_history"][-1]["reason"]

    # The prompt carried this exception's evidence and nothing about other loans.
    prompt = fake.calls[0][1]["content"]
    assert all(i["evidence_id"] in prompt for i in items)
    assert "LN-1004" not in prompt and "LN-1010" not in prompt
    assert fake.schemas[0]["additionalProperties"] is False

    # The loan records themselves are untouched.
    loan = client.get("/api/loans/LN-1001").json()
    assert loan["downstream"]["product_code_raw"] == "TERM" and loan["downstream"]["version"] == 1


# --- 2. Mapping rule does not explain the discrepancy ---------------------------


def test_2_mapping_does_not_explain(client, exceptions_ready, use_llm):
    items = _items(client, "EXC-00010")
    rule = ids_of(items, "MAPPING_RULE")[0]
    map_finding = [i["evidence_id"] for i in items if i["retrieval_method"] == "SAME_LOAN_FINDING"][0]
    down, clause = ids_of(items, "DOWNSTREAM_RECORD")[0], ids_of(items, "AGREEMENT_CLAUSE")[0]
    history = ids_of(items, "HISTORICAL_CASE", "HX-2025-0090")[0]

    use_llm(FakeLlm(as_json(report(
        "EXC-00010",
        confirmed_facts=[fact("Active mapping PRODMAP-v2 maps Bridge Loan to BRIDGE, but TERM was booked.",
                              [rule, down, map_finding])],
        probable_causes=[
            cause("The configured mapping produced the discrepancy.", [], claim_type="UNVERIFIED_POSSIBILITY",
                  contradicting=[rule, map_finding], confidence="low"),
            cause("The product was overridden manually after mapping, possibly because the agreement calls it "
                  "a 'bridge term loan'.", [clause, map_finding], confidence="low"),
            cause("Same unexplained pattern as a past bridge/term case.", [history],
                  claim_type="UNVERIFIED_POSSIBILITY", confidence="low"),
        ],
        recommended_checks=[check("Review the booking audit trail for manual edits to the product.", [down])],
        missing_information=[{"item": "Loan IQ booking audit log", "why_needed": "Shows whether the product was edited."}],
        overall_assessment="The mapping rule does not explain the discrepancy; the cause is not yet determined.",
    ))))

    body = _investigate(client, "EXC-00010").json()
    assert body["status"] == "SUCCEEDED"
    mapping_cause = body["report"]["probable_causes"][0]
    assert mapping_cause["contradicting_evidence_ids"] == [rule, map_finding]
    assert mapping_cause["claim_type"] == "UNVERIFIED_POSSIBILITY"


# --- 3. Conflicting evidence -------------------------------------------------------


def test_3_conflicting_evidence_is_surfaced(client, exceptions_ready, use_llm):
    items = _items(client, "EXC-00003")
    up, down = ids_of(items, "UPSTREAM_RECORD")[0], ids_of(items, "DOWNSTREAM_RECORD")[0]
    original = ids_of(items, "AGREEMENT_CLAUSE", "CL-FA1003-2.1")[0]
    amendment = ids_of(items, "AGREEMENT_CLAUSE", "CL-AMD1003-01-3")[0]

    use_llm(FakeLlm(as_json(report(
        "EXC-00003",
        confirmed_facts=[fact("Amendment AMD-1003-01 reduces commitments to USD 20,000,000 from 15 June 2025.",
                              [amendment])],
        conflicting_evidence=[{
            "description": "Upstream (25m) agrees with the original agreement; downstream (20m) agrees with the amendment.",
            "evidence_ids": [up, original, down, amendment],
        }],
        probable_causes=[cause("The upstream record was not updated after the amendment.", [amendment, down],
                               contradicting=[up])],
        recommended_checks=[check("Confirm the amendment was executed and is effective.", [amendment])],
    ))))

    body = _investigate(client, "EXC-00003").json()
    assert body["status"] == "SUCCEEDED"
    assert body["report"]["conflicting_evidence"][0]["evidence_ids"] == [up, original, down, amendment]


# --- 4. Missing contractual evidence ------------------------------------------------


def test_4_missing_contract_yields_insufficient(client, exceptions_ready, use_llm):
    items = _items(client, "EXC-00004")
    up, down = ids_of(items, "UPSTREAM_RECORD")[0], ids_of(items, "DOWNSTREAM_RECORD")[0]
    fake = use_llm(FakeLlm(as_json(report(
        "EXC-00004",
        evidence_sufficiency="INSUFFICIENT",
        confirmed_facts=[fact("Upstream is EUR and downstream is USD.", [up, down])],
        probable_causes=[],
        recommended_checks=[check("Obtain the executed facility agreement for LN-1004.", [], basis="MISSING_INFORMATION")],
        missing_information=[{"item": "Executed facility agreement", "why_needed": "States the agreed currency."}],
        escalation={"recommended": True, "reason": "Critical currency mismatch with no contractual evidence."},
        overall_assessment="The root cause cannot be established from the available information.",
    ))))

    body = _investigate(client, "EXC-00004").json()
    rep = body["report"]
    assert rep["evidence_sufficiency"] == "INSUFFICIENT"
    assert rep["root_cause_statement"] == INSUFFICIENT_STATEMENT
    assert rep["escalation"]["recommended"] is True
    assert "No facility agreement or amendment clauses are on file for LN-1004." in fake.calls[0][1]["content"]


# --- 5. Fabricated evidence id --------------------------------------------------------


def _fabricated(exception_id, real_id):
    return as_json(report(
        exception_id,
        probable_causes=[cause("Mapping defect confirmed by clause 9.4.", [real_id, "EV-99999"])],
        recommended_checks=[check("Read clause 9.4.", ["EV-99999"])],
    ))


def test_5_fabricated_evidence_id_fails_after_bounded_retries(client, exceptions_ready, use_llm):
    real = ids_of(_items(client, "EXC-00001"), "MAPPING_RULE")[0]
    fake = use_llm(FakeLlm(_fabricated("EXC-00001", real), _fabricated("EXC-00001", real)))

    response = _investigate(client, "EXC-00001")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error_code"] == "INVALID_OUTPUT"
    assert len(fake.calls) == 2  # bounded: max_attempts

    audit = client.get(f"/api/investigations/{detail['investigation_id']}").json()
    assert audit["status"] == "FAILED" and audit["report"] is None
    assert len(audit["raw_responses"]) == 2
    assert any("EV-99999" in e for e in audit["validation_errors"][0]["errors"])
    assert _status(client, "EXC-00001") == "OPEN"  # unchanged on failure


def test_5b_retry_with_feedback_recovers(client, exceptions_ready, use_llm):
    items = _items(client, "EXC-00001")
    real = ids_of(items, "MAPPING_RULE")[0]
    good = as_json(report("EXC-00001", probable_causes=[cause("Retired mapping applied.", [real])],
                          recommended_checks=[check("Verify mapping version.", [real])]))
    fake = use_llm(FakeLlm(_fabricated("EXC-00001", real), good))

    body = _investigate(client, "EXC-00001").json()
    assert (body["status"], body["attempts"]) == ("SUCCEEDED", 2)
    assert len(body["validation_errors"]) == 1
    feedback = fake.calls[1][-1]["content"]
    assert "rejected by validation" in feedback and "EV-99999" in feedback


# --- 6. Ollama unavailable / model missing / timeout ------------------------------------


@pytest.mark.parametrize(
    "error, http_status, code",
    [
        (LlmUnavailable("Cannot reach Ollama"), 503, "OLLAMA_UNAVAILABLE"),
        (LlmModelNotFound("Model 'x' is not available"), 503, "MODEL_NOT_FOUND"),
        (LlmTimeout("No response within 180s"), 504, "TIMEOUT"),
    ],
)
def test_6_service_failures_are_controlled_and_not_retried(client, exceptions_ready, use_llm, error, http_status, code):
    fake = use_llm(FakeLlm(error, "never used"))
    response = _investigate(client, "EXC-00001")
    assert response.status_code == http_status
    assert response.json()["detail"]["error_code"] == code
    assert len(fake.calls) == 1
    listed = client.get("/api/exceptions/EXC-00001/investigations").json()
    assert [(i["status"], i["error_code"]) for i in listed] == [("FAILED", code)]
    assert _status(client, "EXC-00001") == "OPEN"


def test_6b_ai_status_endpoint(client, use_llm):
    use_llm(FakeLlm(list_error=LlmUnavailable("Cannot reach Ollama at http://127.0.0.1:11434")))
    down = client.get("/api/ai/status").json()
    assert (down["reachable"], down["error_code"]) == (False, "OLLAMA_UNAVAILABLE")

    use_llm(FakeLlm(models=["llama3.1:latest"]))
    missing = client.get("/api/ai/status").json()
    assert (missing["reachable"], missing["model_available"], missing["error_code"]) == (True, False, "MODEL_NOT_FOUND")

    use_llm(FakeLlm())
    assert client.get("/api/ai/status").json()["model_available"] is True


# --- 7. Invalid structured output ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad_output, expected_fragment",
    [
        ("I think the mapping is wrong.", "not valid JSON"),
        ('{"exception_id": "EXC-00001", "summary": "x"}', "Field required"),
        ('{"exception_id": "EXC-00001", "summary": "x", "evidence_sufficiency": "MAYBE"}', "evidence_sufficiency"),
    ],
)
def test_7_invalid_structured_output(client, exceptions_ready, use_llm, bad_output, expected_fragment):
    use_llm(FakeLlm(bad_output, bad_output))
    response = _investigate(client, "EXC-00001")
    assert response.status_code == 502
    audit = client.get(f"/api/investigations/{response.json()['detail']['investigation_id']}").json()
    assert any(expected_fragment in e for e in audit["validation_errors"][-1]["errors"])


# --- Further safeguards ------------------------------------------------------------------


def test_history_only_cause_is_rejected(client, exceptions_ready, use_llm):
    history = ids_of(_items(client, "EXC-00001"), "HISTORICAL_CASE")[0]
    bad = as_json(report("EXC-00001", probable_causes=[cause("Same as the past case.", [history], confidence="high")],
                         recommended_checks=[check("Compare with the past case.", [history])]))
    use_llm(FakeLlm(bad, bad), max_attempts=2)
    response = _investigate(client, "EXC-00001")
    assert response.status_code == 502


def test_closed_exception_cannot_be_investigated(client, exceptions_ready, use_llm):
    fake = use_llm(FakeLlm())
    client.patch("/api/exceptions/EXC-00002/status",
                 json={"to_status": "REJECTED", "actor": "analyst.test", "reason": "Known artefact"})
    assert _investigate(client, "EXC-00002").status_code == 409
    assert fake.calls == []


def test_system_requester_rejected(client, exceptions_ready, use_llm):
    use_llm(FakeLlm())
    assert _investigate(client, "EXC-00001", by="system:bot").status_code == 422


def test_reinvestigation_and_audit_record(client, exceptions_ready, use_llm):
    real = ids_of(_items(client, "EXC-00001"), "MAPPING_RULE")[0]
    good = as_json(report("EXC-00001", probable_causes=[cause("Retired mapping applied.", [real])],
                          recommended_checks=[check("Update the Loan IQ product to REVOLVER.", [real])]))
    use_llm(FakeLlm(good, good))
    first = _investigate(client, "EXC-00001").json()
    second = _investigate(client, "EXC-00001").json()
    assert (first["investigation_id"], second["investigation_id"]) == ("AI-00001", "AI-00002")
    assert second["report"]["policy_flags"][0].startswith("recommended_checks[0] appears to prescribe a change")

    audit = client.get("/api/investigations/AI-00002").json()
    assert audit["evidence_package"]["exception_id"] == "EXC-00001"
    assert len(audit["prompt_sha256"]) == 64
    assert [i["investigation_id"] for i in client.get("/api/exceptions/EXC-00001/investigations").json()] == [
        "AI-00002", "AI-00001"]
    assert _status(client, "EXC-00001") == "RECOMMENDATION_GENERATED"


def test_sufficient_with_only_unverified_causes_is_retried_to_insufficient(client, exceptions_ready, use_llm):
    """EVAL-00002 S06 pattern: 'sufficient' + only unverified causes is rejected; the retry is accepted."""
    unverified = cause("The upstream record was not populated.", [], claim_type="UNVERIFIED_POSSIBILITY", confidence="low")
    first = as_json(report("EXC-00006", probable_causes=[unverified],
                           recommended_checks=[check("Obtain the first utilisation date.", [], basis="MISSING_INFORMATION")]))
    second = as_json(report("EXC-00006", evidence_sufficiency="INSUFFICIENT", probable_causes=[unverified],
                            recommended_checks=[check("Obtain the first utilisation date.", [], basis="MISSING_INFORMATION")]))
    fake = use_llm(FakeLlm(first, second))

    body = _investigate(client, "EXC-00006").json()
    assert (body["status"], body["attempts"]) == ("SUCCEEDED", 2)
    assert any("requires at least one EVIDENCE_SUPPORTED_HYPOTHESIS" in e for e in body["validation_errors"][0]["errors"])
    assert body["report"]["root_cause_statement"] == INSUFFICIENT_STATEMENT
    assert "requires at least one EVIDENCE_SUPPORTED_HYPOTHESIS" in fake.calls[1][-1]["content"]
