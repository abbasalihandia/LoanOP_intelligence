"""Phase 3: evidence retrieval, stable IDs, gaps and traceability."""

import pytest
from sqlalchemy import func, select

from app.db.models import EvidenceItem, HistoricalException, MappingRule
from app.validation.config import get_validation_config
from app.validation.runner import run_validation
from tests.ai_helpers import ids_of


@pytest.fixture
def exceptions_ready(db, seed_report):
    run_validation(db, get_validation_config())


def _package(client, exception_id):
    response = client.get(f"/api/exceptions/{exception_id}/evidence")
    assert response.status_code == 200
    return response.json()


def _refs(package):
    return [(i["evidence_type"], i["source_reference"].split(":")[-1]) for i in package["items"]]


def test_ln1001_product_package(client, exceptions_ready):
    package = _package(client, "EXC-00001")
    assert _refs(package) == [
        ("VALIDATION_FINDING", "EXC-00001"),
        ("UPSTREAM_RECORD", "v2"),
        ("DOWNSTREAM_RECORD", "v1"),
        ("VALIDATION_FINDING", "EXC-00002"),  # the MAP-002 finding on the same loan
        ("MAPPING_RULE", "MAP-PROD-V1-001"),  # recorded on the downstream record
        ("MAPPING_RULE", "MAP-PROD-V2-001"),  # currently active
        ("AGREEMENT_CLAUSE", "CL-FA1001-2.1"),  # the termination-date clause is not relevant
        ("HISTORICAL_CASE", "HX-2024-0117"),
        ("HISTORICAL_CASE", "HX-2025-0090"),
    ]
    assert package["gaps"] == []
    assert [i["evidence_id"] for i in package["items"]] == [f"EV-{n:05d}" for n in range(1, 10)]

    # Deterministic timeline: LN-1001 was last updated 2025-02-10, while v1 was still effective.
    recorded, active = package["items"][4]["relevance"], package["items"][5]["relevance"]
    assert "last updated on 2025-02-10, within this rule's effective period (2024-01-01 to 2025-02-28)" in recorded
    assert "last updated on 2025-02-10, before this rule became effective on 2025-03-01" in active
    history = package["items"][7]
    assert history["score"] == 9 and "Not proof of the current cause" in history["relevance"]


def test_ln1010_package_contains_mapping_that_does_not_explain(client, exceptions_ready):
    package = _package(client, "EXC-00010")
    [rule] = [i for i in package["items"] if i["evidence_type"] == "MAPPING_RULE"]
    assert rule["content"]["rule_id"] == "MAP-PROD-V2-003"
    assert rule["content"]["target_value"] == "BRIDGE"
    related = [i["content"]["rule_id"] for i in package["items"] if i["retrieval_method"] == "SAME_LOAN_FINDING"]
    assert related == ["RULE-MAP-001"]


def test_ln1003_amount_package_includes_amendment(client, exceptions_ready):
    package = _package(client, "EXC-00003")
    clauses = [i["content"]["clause_id"] for i in package["items"] if i["evidence_type"] == "AGREEMENT_CLAUSE"]
    assert clauses == ["CL-AMD1003-01-3", "CL-FA1003-2.1"]
    assert ids_of(package["items"], "MAPPING_RULE") == []  # mapping only for product exceptions


def test_ln1004_reports_missing_contractual_evidence(client, exceptions_ready):
    package = _package(client, "EXC-00004")
    assert [i["evidence_type"] for i in package["items"]] == [
        "VALIDATION_FINDING", "UPSTREAM_RECORD", "DOWNSTREAM_RECORD",
    ]
    assert package["gaps"] == [
        "No facility agreement or amendment clauses are on file for LN-1004.",
        "No sufficiently similar historical cases were found.",
    ]


def test_ln1008_reports_missing_downstream(client, exceptions_ready):
    gaps = _package(client, "EXC-00008")["gaps"]
    assert gaps[0] == "No downstream record exists for LN-1008."


def test_retrieval_is_idempotent_and_ids_are_shared(db, client, exceptions_ready):
    first = _package(client, "EXC-00001")
    count = db.scalar(select(func.count(EvidenceItem.id)))
    second = _package(client, "EXC-00001")
    assert [i["evidence_id"] for i in first["items"]] == [i["evidence_id"] for i in second["items"]]
    assert db.scalar(select(func.count(EvidenceItem.id))) == count

    other = _package(client, "EXC-00002")
    upstream_1001 = ids_of(first["items"], "UPSTREAM_RECORD")
    assert ids_of(other["items"], "UPSTREAM_RECORD") == upstream_1001


def test_unknown_exception_evidence_404(client, exceptions_ready):
    assert client.get("/api/exceptions/EXC-99999/evidence").status_code == 404
    assert client.get("/api/evidence/EV-99999").status_code == 404


def test_traceability_current_changed_missing(db, client, exceptions_ready):
    package = _package(client, "EXC-00001")
    rule_id = ids_of(package["items"], "MAPPING_RULE", "MAP-PROD-V1-001")[0]
    history_id = ids_of(package["items"], "HISTORICAL_CASE", "HX-2024-0117")[0]
    upstream_id = ids_of(package["items"], "UPSTREAM_RECORD")[0]

    assert client.get(f"/api/evidence/{rule_id}").json()["traceability_status"] == "CURRENT"

    rule = db.scalar(select(MappingRule).where(MappingRule.rule_id == "MAP-PROD-V1-001"))
    rule.notes = "Edited after the evidence was captured."
    db.delete(db.scalar(select(HistoricalException).where(HistoricalException.case_id == "HX-2024-0117")))
    db.commit()

    changed = client.get(f"/api/evidence/{rule_id}").json()
    assert changed["traceability_status"] == "SOURCE_CHANGED"
    assert changed["evidence"]["content"]["notes"] == "Superseded by PRODMAP-v2 on 2025-03-01."  # snapshot kept
    assert client.get(f"/api/evidence/{history_id}").json()["traceability_status"] == "SOURCE_MISSING"
    assert client.get(f"/api/evidence/{upstream_id}").json()["traceability_status"] == "CURRENT"
