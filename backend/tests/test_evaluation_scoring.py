"""Pure tests for Phase 7 scoring and the time-estimate model."""

from pathlib import Path

from app.evaluation.baseline import BaselineModel, summarise_estimates
from app.evaluation.scenarios import SCENARIOS, scenario_by_id
from app.evaluation.scoring import evidence_id_for_key, quality_metrics, score_report

BASELINE = BaselineModel.load(Path(__file__).resolve().parents[1] / "config" / "manual_baseline_estimates.json")


def _item(eid, etype, ref, content=None):
    return {"evidence_id": eid, "evidence_type": etype, "source_reference": ref, "content": content or {}}


LN1001 = {"items": [
    _item("EV-00001", "VALIDATION_FINDING", "validation:exceptions:EXC-00001", {"exception_id": "EXC-00001"}),
    _item("EV-00002", "UPSTREAM_RECORD", "NCINO_SIM:loan_records:LN-1001:v2"),
    _item("EV-00003", "DOWNSTREAM_RECORD", "LOANIQ_SIM:loan_records:LN-1001:v1"),
    _item("EV-00004", "VALIDATION_FINDING", "validation:exceptions:EXC-00002", {"exception_id": "EXC-00002"}),
    _item("EV-00005", "MAPPING_RULE", "reference:mapping_rules:MAP-PROD-V1-001",
          {"rule_id": "MAP-PROD-V1-001", "mapping_version": "PRODMAP-v1"}),
    _item("EV-00006", "MAPPING_RULE", "reference:mapping_rules:MAP-PROD-V2-001",
          {"rule_id": "MAP-PROD-V2-001", "mapping_version": "PRODMAP-v2"}),
    _item("EV-00007", "AGREEMENT_CLAUSE", "reference:agreement_clauses:CL-FA1001-2.1",
          {"clause_id": "CL-FA1001-2.1", "document_ref": "FA-1001"}),
]}


def cause(text, supporting, contradicting=(), claim="EVIDENCE_SUPPORTED_HYPOTHESIS", confidence="medium", reasoning=""):
    return {"cause": text, "claim_type": claim, "supporting_evidence_ids": list(supporting),
            "contradicting_evidence_ids": list(contradicting), "reasoning": reasoning, "confidence": confidence}


def report(**overrides):
    base = {"summary": "", "evidence_sufficiency": "SUFFICIENT_FOR_HYPOTHESIS", "confirmed_facts": [],
            "probable_causes": [], "alternative_explanations": [], "conflicting_evidence": [],
            "recommended_checks": [], "missing_information": [], "uncertainties": [],
            "escalation": {"recommended": False, "reason": "x"}, "overall_assessment": "", "policy_flags": []}
    base.update(overrides)
    return base


# --- Replaying the live AI-00003 (llama3.1) report for EXC-00002 --------------------


AI_00003 = report(
    confirmed_facts=[{"statement": "Downstream references PRODMAP-v1.", "evidence_ids": ["EV-00004"]},
                     {"statement": "Active PRODMAP-v2 maps to REVOLVER.", "evidence_ids": ["EV-00006"]}],
    probable_causes=[cause("The downstream record is using a retired mapping version 'PRODMAP-v1' that maps "
                           "'Revolving Credit' to 'TERM'.", ["EV-00004", "EV-00005"], ["EV-00006"], confidence="high")],
    conflicting_evidence=[{"description": "v2 contradicts the hypothesis", "evidence_ids": ["EV-00006", "EV-00004"]}],
    recommended_checks=[{"step": "Check the clause", "purpose": "x", "basis": "EVIDENCE", "evidence_ids": ["EV-00007"]},
                        {"step": "Check mapping rules", "purpose": "x", "basis": "EVIDENCE", "evidence_ids": ["EV-00005", "EV-00006"]}],
    missing_information=[{"item": "The effective date of the facility agreement clause 'CL-FA1001-2.1'.",
                          "why_needed": "To confirm it is still in effect."}],
)


def test_live_ai_00003_report_is_scored_as_observed_by_review():
    result = score_report(scenario_by_id("S02"), AI_00003, LN1001)
    by_name = {c.name: c.passed for c in result.checks}
    assert by_name["expected_cause_found"] is True
    assert by_name["cites MAP-PROD-V1-001"] is True and by_name["cites MAP-PROD-V2-001"] is True
    assert by_name["does not treat MAP-PROD-V2-001 as contradicting"] is False  # the error found in review
    assert result.score == round(5 / 6, 3)
    assert result.metrics["high_confidence_with_contradiction"] == 1
    assert result.metrics["possibly_false_missing_information"] == 1  # the clause date was in the evidence
    assert result.metrics["invalid_citations"] == 0


# --- Scenario checks --------------------------------------------------------------------


def test_no_report_scores_zero():
    result = score_report(scenario_by_id("S01"), None, LN1001)
    assert result.score == 0.0 and result.checks[0].name == "valid_report"


def test_s01_good_report_scores_full():
    good = report(probable_causes=[cause("Booked under the retired PRODMAP-v1 mapping rule.", ["EV-00005", "EV-00004"])])
    assert score_report(scenario_by_id("S01"), good, LN1001).score == 1.0


def test_restated_discrepancy_does_not_count_as_expected_cause():
    restated = report(probable_causes=[cause("The product type mismatch between the records.", ["EV-00001"])])
    by_name = {c.name: c.passed for c in score_report(scenario_by_id("S01"), restated, LN1001).checks}
    assert by_name["expected_cause_found"] is False
    assert by_name["cites MAP-PROD-V1-001"] is False


def test_must_cite_absent_from_package_is_not_applicable():
    result = score_report(scenario_by_id("S03"), report(), {"items": []})
    amendment = next(c for c in result.checks if c.name == "cites CL-AMD1003-01-3")
    assert amendment.passed is None


def test_s04_insufficient_report_passes_and_overclaiming_fails():
    package = {"items": [_item("EV-00010", "UPSTREAM_RECORD", "NCINO_SIM:loan_records:LN-1004:v1")]}
    good = report(evidence_sufficiency="INSUFFICIENT",
                  missing_information=[{"item": "Executed facility agreement", "why_needed": "States the currency."}])
    assert score_report(scenario_by_id("S04"), good, package).score == 1.0

    bad = report(probable_causes=[cause("Keying error in Loan IQ.", ["EV-00010"], confidence="high")])
    by_name = {c.name: c.passed for c in score_report(scenario_by_id("S04"), bad, package).checks}
    assert by_name["evidence_sufficiency"] is False
    assert by_name["no_high_confidence"] is False
    assert by_name["asks_for_missing_information"] is False


def test_s10_blaming_the_correct_mapping_fails_but_negation_passes():
    package = {"items": [_item("EV-00020", "MAPPING_RULE", "reference:mapping_rules:MAP-PROD-V2-003")]}
    blamed = report(probable_causes=[cause("Incorrect product mapping applied.", ["EV-00020"])])
    cleared = report(probable_causes=[cause("The mapping does not explain the discrepancy.", [], ["EV-00020"],
                                            claim="UNVERIFIED_POSSIBILITY", confidence="low")],
                     recommended_checks=[{"step": "x", "purpose": "y", "basis": "EVIDENCE", "evidence_ids": ["EV-00020"]}])
    check = "does_not_blame_correct_mapping"
    assert {c.name: c.passed for c in score_report(scenario_by_id("S10"), blamed, package).checks}[check] is False
    assert {c.name: c.passed for c in score_report(scenario_by_id("S10"), cleared, package).checks}[check] is True


def test_conflict_expected_for_s03():
    package = {"items": [_item("EV-00030", "AGREEMENT_CLAUSE", "reference:agreement_clauses:CL-AMD1003-01-3")]}
    no_conflict = report(probable_causes=[cause("Upstream not updated after the amendment.", ["EV-00030"])])
    by_name = {c.name: c.passed for c in score_report(scenario_by_id("S03"), no_conflict, package).checks}
    assert by_name["expected_cause_found"] is True and by_name["conflict_flagged"] is False


def test_uncited_mention_detected():
    text_only = report(overall_assessment="See clause CL-FA1001-2.1 for the facility type.")
    assert quality_metrics(text_only, LN1001)["uncited_mentions"] == ["cl-fa1001-2.1"]


def test_evidence_lookup_by_key():
    assert evidence_id_for_key(LN1001, "map-prod-v2-001") == "EV-00006"
    assert evidence_id_for_key(LN1001, "NOPE") is None


def test_scenarios_cover_all_seeded_exceptions_once():
    keys = [(s.loan_id, s.rule_id) for s in SCENARIOS]
    assert len(keys) == len(set(keys)) == 11
    assert [s.scenario_id for s in SCENARIOS] == [f"S{n:02d}" for n in range(1, 12)]


# --- Time estimate (ESTIMATE, not measurement) -----------------------------------------


CATEGORIES = ["PRODUCT_MISMATCH", "MAPPING_INCONSISTENCY", "AMOUNT_MISMATCH", "CURRENCY_MISMATCH", "MATURITY_MISMATCH",
              "MISSING_FIELD", "BOOKING_FAILURE", "MISSING_DOWNSTREAM", "DATA_TYPE", "PRODUCT_MISMATCH",
              "MAPPING_INCONSISTENCY"]


def test_estimate_per_category():
    booking = BASELINE.estimate("BOOKING_FAILURE", model_seconds=240)
    assert booking.manual_minutes == 53
    assert booking.ai_analyst_minutes == 28  # 10 review + 3 resolution + 15 static-data check still manual
    assert booking.model_minutes_measured == 4.0
    assert BASELINE.estimate("DATA_TYPE").manual_minutes == 16


def test_estimate_totals_for_the_eleven_scenarios():
    summary = summarise_estimates([BASELINE.estimate(c) for c in CATEGORIES])
    assert (summary["manual_minutes"], summary["ai_assisted_analyst_minutes"]) == (429, 159)
    assert summary["analyst_time_reduction_pct"] == 62.9
    assert summary["ai_assisted_analyst_minutes_pessimistic"] == 260
    assert summary["analyst_time_reduction_pct_pessimistic"] == 39.4
    assert summary["label"].startswith("ESTIMATE")
