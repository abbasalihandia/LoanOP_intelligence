"""Phase 7 runner over the real seeded scenarios with a scripted fake model."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.ai.errors import LlmUnavailable
from app.db.models import AiInvestigation
from app.evaluation.baseline import BaselineModel
from app.evaluation.runner import export_run, run_evaluation
from app.evaluation.scenarios import SCENARIOS
from app.validation.config import get_validation_config
from app.validation.runner import run_validation
from tests.ai_helpers import FakeLlm, check, report

BASELINE = BaselineModel.load(Path(__file__).resolve().parents[1] / "config" / "manual_baseline_estimates.json")


def insufficient_report(messages):
    """A valid, cautious report for whichever exception is being investigated."""
    exception_id = re.search(r"exception_id (EXC-\d{5})\.", messages[-1]["content"]).group(1)
    return json.dumps(report(
        exception_id,
        evidence_sufficiency="INSUFFICIENT",
        probable_causes=[],
        recommended_checks=[check("Obtain the executed facility agreement.", [], basis="MISSING_INFORMATION")],
        missing_information=[{"item": "Executed facility agreement", "why_needed": "Confirms the agreed terms."}],
        overall_assessment="The root cause cannot be established from the available information.",
    ))


@pytest.fixture
def validated(db, seed_report):
    run_validation(db, get_validation_config())


def test_full_run_is_isolated_from_operations(db, client, validated, tmp_path):
    fake = FakeLlm(*[insufficient_report] * 11)
    statuses_before = [e["status"] for e in client.get("/api/exceptions").json()]

    run = run_evaluation(db, fake, max_attempts=1, baseline=BASELINE)

    assert (run.run_id, run.status, run.scenario_count) == ("EVAL-00001", "COMPLETED", 11)
    assert len(fake.calls) == 11
    summary = run.summary
    assert (summary["succeeded"], summary["failed"], summary["skipped"]) == (11, 0, 0)
    assert summary["validation"]["valid_first_attempt"] == 11
    assert summary["quality"]["invalid_citations"] == 0
    assert summary["time_estimate"]["summary"]["manual_minutes"] == 429

    # The insufficient-evidence scenarios score fully; the cause-finding ones do not.
    scores = {row["scenario_id"]: row["score"] for row in summary["per_scenario"]}
    assert scores["S04"] == 1.0 and scores["S01"] < 1.0

    # Operations untouched: no AI investigations, no status changes.
    assert db.scalar(select(func.count(AiInvestigation.id))) == 0
    assert [e["status"] for e in client.get("/api/exceptions").json()] == statuses_before

    path = export_run(db, run, tmp_path)
    exported = json.loads(path.read_text())
    assert exported["run_id"] == "EVAL-00001" and len(exported["results"]) == 11
    assert exported["results"][0]["report"]["evidence_sufficiency"] == "INSUFFICIENT"

    api = client.get("/api/evaluations/EVAL-00001").json()
    assert len(api["results"]) == 11 and api["summary"]["succeeded"] == 11
    assert client.get("/api/evaluations").json()[0]["run_id"] == "EVAL-00001"


def test_unavailable_model_aborts_early(db, validated):
    fake = FakeLlm(LlmUnavailable("Cannot reach Ollama"))
    run = run_evaluation(db, fake, max_attempts=2, baseline=BASELINE, scenarios=SCENARIOS[:4])
    assert run.status == "ABORTED"
    assert len(fake.calls) == 1
    rows = run.summary["per_scenario"]
    assert [r["status"] for r in rows] == ["FAILED", "SKIPPED", "SKIPPED", "SKIPPED"]
    assert rows[1]["error_code"] == "OLLAMA_UNAVAILABLE"


def test_scenarios_without_exceptions_are_skipped(db, seed_report):
    fake = FakeLlm()
    run = run_evaluation(db, fake, max_attempts=1, baseline=BASELINE, scenarios=SCENARIOS[:2])
    assert fake.calls == []
    assert [r["error_code"] for r in run.summary["per_scenario"]] == ["NO_EXCEPTION", "NO_EXCEPTION"]


def test_resolved_exceptions_are_still_evaluated(db, client, validated):
    clause = [i for i in client.get("/api/exceptions/EXC-00005/evidence").json()["items"]
              if i["evidence_type"] == "AGREEMENT_CLAUSE"][0]["evidence_id"]
    client.patch("/api/exceptions/EXC-00005/status", json={"to_status": "UNDER_INVESTIGATION", "actor": "analyst.t"})
    assert client.post("/api/exceptions/EXC-00005/resolution", json={
        "resolved_by": "analyst.t", "analyst_decision": "NO_AI_REPORT", "root_cause_category": "MANUAL_KEYING_ERROR",
        "confirmed_root_cause": "Day keyed as 01 instead of 31.", "record_in_error": "DOWNSTREAM",
        "final_action": "Corrected in Loan IQ.", "outcome": "CORRECTED_IN_SOURCE", "evidence_ids": [clause],
    }).status_code == 201

    s05 = [s for s in SCENARIOS if s.scenario_id == "S05"]
    run = run_evaluation(db, FakeLlm(insufficient_report), max_attempts=1, baseline=BASELINE, scenarios=s05)
    assert run.summary["per_scenario"][0]["status"] == "SUCCEEDED"
    assert client.get("/api/exceptions/EXC-00005").json()["status"] == "RESOLVED"
