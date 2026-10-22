"""Pure rule tests: no database, no API."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.validation.config import ValidationConfigError, load_validation_config, parse_validation_config
from app.validation.mapping import MappingIndex
from app.validation.model import LoanSnapshot, MappingRuleView, Side
from app.validation.rules import RULES, evaluate_loan
from app.validation.severity import assign_severity

CONFIG = load_validation_config(Path(__file__).resolve().parents[1] / "config" / "validation_rules.json")

INDEX = MappingIndex([
    MappingRuleView("MAP-PROD-V1-001", "PRODMAP", "PRODMAP-v1", "Revolving Credit", "TERM", "RETIRED"),
    MappingRuleView("MAP-PROD-V1-002", "PRODMAP", "PRODMAP-v1", "Term Loan", "TERM", "RETIRED"),
    MappingRuleView("MAP-PROD-V2-001", "PRODMAP", "PRODMAP-v2", "Revolving Credit", "REVOLVER", "ACTIVE"),
    MappingRuleView("MAP-PROD-V2-002", "PRODMAP", "PRODMAP-v2", "Term Loan", "TERM", "ACTIVE"),
    MappingRuleView("MAP-PROD-V2-003", "PRODMAP", "PRODMAP-v2", "Bridge Loan", "BRIDGE", "ACTIVE"),
])

UP = LoanSnapshot(
    loan_id="LN-1", source_system="NCINO_SIM", record_id=1, facility_id="FAC-1",
    product_type="TERM_LOAN", product_code_raw="Term Loan", currency="USD",
    amount=Decimal("1000000"), maturity_date=date(2030, 6, 30), status="APPROVED",
)
DOWN = LoanSnapshot(
    loan_id="LN-1", source_system="LOANIQ_SIM", record_id=2, facility_id="FAC-1",
    product_type="TERM_LOAN", product_code_raw="TERM", currency="USD",
    amount=Decimal("1000000.00"), maturity_date=date(2030, 6, 30), status="BOOKED",
    mapping_version="PRODMAP-v2",
)


def run(up=UP, down=DOWN):
    findings = evaluate_loan(up, down, INDEX, CONFIG)
    for f in findings:
        f.severity = assign_severity(f, CONFIG)
    return findings


def rules_of(findings):
    return [f.rule_id for f in findings]


# --- Clean case ------------------------------------------------------------


def test_matching_records_produce_no_findings():
    assert run() == []


def test_amount_formatting_difference_is_not_a_mismatch():
    assert run(down=replace(DOWN, amount=Decimal("1000000.0000"))) == []


# --- Required fields and data types ---------------------------------------


def test_missing_upstream_maturity_is_required_field_finding():
    [f] = run(up=replace(UP, maturity_date=None))
    assert (f.rule_id, f.side, f.field_name) == ("RULE-REQ-001", Side.UPSTREAM, "maturity_date")
    assert f.source_value is None and f.target_value == "2030-06-30"
    assert f.severity == "HIGH"


def test_unparseable_value_is_type_finding_not_required_finding():
    issue = {"field": "amount", "raw_value": "1,OOO,000", "issue": "Not a valid decimal amount"}
    [f] = run(down=replace(DOWN, amount=None, normalization_issues=(issue,)))
    assert (f.rule_id, f.side, f.field_name) == ("RULE-TYPE-001", Side.DOWNSTREAM, "amount")
    assert f.target_value == "1,OOO,000"
    assert f.source_value == "1000000"


def test_missing_downstream_mapping_version_is_required_and_skips_mapping_rules():
    findings = run(down=replace(DOWN, mapping_version=None))
    assert rules_of(findings) == ["RULE-REQ-001"]
    assert findings[0].field_name == "mapping_version"


# --- Comparisons -----------------------------------------------------------


def test_product_mismatch_reports_raw_values_neutrally():
    findings = run(up=replace(UP, product_type="BRIDGE_LOAN", product_code_raw="Bridge Loan"))
    product = next(f for f in findings if f.rule_id == "RULE-PRODUCT-001")
    assert (product.source_value, product.target_value) == ("Bridge Loan", "TERM")
    assert "upstream" in product.explanation and "downstream" in product.explanation
    assert "incorrect" not in product.explanation.lower()


def test_currency_mismatch_is_critical():
    [f] = run(down=replace(DOWN, currency="EUR"))
    assert (f.rule_id, f.severity) == ("RULE-CCY-001", "CRITICAL")


def test_small_amount_difference_is_high():
    [f] = run(down=replace(DOWN, amount=Decimal("990000")))
    assert f.rule_id == "RULE-AMT-001"
    assert f.details["metrics"] == {"abs_difference": "10000", "pct_difference": "1.00"}
    assert f.severity == "HIGH"


def test_large_amount_difference_escalates_to_critical():
    [f] = run(down=replace(DOWN, amount=Decimal("800000")))
    assert f.details["metrics"]["pct_difference"] == "20.00"
    assert f.severity == "CRITICAL"


def test_amount_within_tolerance_is_ignored():
    assert run(down=replace(DOWN, amount=Decimal("1000000.01"))) == []


def test_maturity_severity_depends_on_days():
    [short] = run(down=replace(DOWN, maturity_date=date(2030, 6, 29)))
    [long] = run(down=replace(DOWN, maturity_date=date(2030, 5, 31)))
    assert (short.severity, short.details["metrics"]["days_difference"]) == ("MEDIUM", 1)
    assert (long.severity, long.details["metrics"]["days_difference"]) == ("HIGH", 30)


# --- Mapping ---------------------------------------------------------------


def test_ln1001_pattern_retired_mapping_applied_as_configured():
    """Revolving Credit booked as TERM under retired v1: product mismatch + MAP-002, but not MAP-001."""
    up = replace(UP, product_type="REVOLVING_CREDIT", product_code_raw="Revolving Credit")
    down = replace(DOWN, mapping_version="PRODMAP-v1")
    findings = run(up, down)
    assert rules_of(findings) == ["RULE-PRODUCT-001", "RULE-MAP-002"]
    map2 = findings[1]
    assert map2.details["active_rule_id"] == "MAP-PROD-V2-001"
    assert map2.details["active_target_value"] == "REVOLVER"


def test_ln1010_pattern_mapping_not_applied_as_configured():
    """Bridge Loan booked as TERM under active v2, which maps to BRIDGE: MAP-001, not MAP-002."""
    up = replace(UP, product_type="BRIDGE_LOAN", product_code_raw="Bridge Loan")
    findings = run(up)
    assert rules_of(findings) == ["RULE-PRODUCT-001", "RULE-MAP-001"]
    assert findings[1].details["expected_target_value"] == "BRIDGE"


def test_retired_mapping_with_same_result_is_not_flagged():
    assert run(down=replace(DOWN, mapping_version="PRODMAP-v1")) == []


def test_unknown_mapping_version():
    [f] = run(down=replace(DOWN, mapping_version="PRODMAP-v9"))
    assert (f.rule_id, f.details["reason"]) == ("RULE-MAP-003", "VERSION_NOT_FOUND")


def test_no_rule_for_source_value():
    up = replace(UP, product_type="LETTER_OF_CREDIT", product_code_raw="Letter of Credit")
    down = replace(DOWN, product_type="LETTER_OF_CREDIT", product_code_raw="SBLC")
    [f] = run(up, down)
    assert (f.rule_id, f.details["reason"]) == ("RULE-MAP-003", "NO_RULE_FOR_SOURCE_VALUE")


# --- Booking ---------------------------------------------------------------


def test_failed_booking():
    [f] = run(down=replace(DOWN, status="FAILED", booking_error="Pricing option missing"))
    assert f.rule_id == "RULE-BOOK-001"
    assert "Pricing option missing" in f.explanation


def test_approved_but_not_booked():
    [f] = run(down=None)
    assert (f.rule_id, f.side, f.downstream_record_id) == ("RULE-BOOK-002", Side.DOWNSTREAM, None)


def test_unapproved_upstream_without_downstream_is_fine():
    assert run(up=replace(UP, status="CREDIT_REVIEW"), down=None) == []


def test_orphan_downstream():
    [f] = run(up=None)
    assert (f.rule_id, f.upstream_record_id) == ("RULE-BOOK-003", None)


# --- Identity and determinism ---------------------------------------------


def test_fingerprint_and_signature():
    [a] = run(down=replace(DOWN, currency="EUR"))
    [b] = run(down=replace(DOWN, currency="GBP"))
    assert a.fingerprint == b.fingerprint == "LN-1|RULE-CCY-001|currency|BOTH"
    assert a.value_signature != b.value_signature


def test_evaluation_is_deterministic():
    up = replace(UP, product_type="BRIDGE_LOAN", product_code_raw="Bridge Loan", currency="EUR")
    first = [(f.rule_id, f.explanation) for f in run(up)]
    second = [(f.rule_id, f.explanation) for f in run(up)]
    assert first == second


def test_every_rule_has_configured_severity():
    assert set(CONFIG.base_severity) == set(RULES)


# --- Config validation -----------------------------------------------------


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda c: c["severity"]["by_rule"].update({"RULE-NOPE": "HIGH"}), "unknown rule"),
        (lambda c: c["severity"].update({"default": "URGENT"}), "severity must be one of"),
        (lambda c: c["tolerances"].update({"amount_absolute": "-1"}), "non-negative"),
        (lambda c: c.pop("statuses"), "Invalid validation configuration"),
    ],
)
def test_invalid_config_rejected(mutation, message):
    import json

    raw = json.loads((Path(__file__).resolve().parents[1] / "config" / "validation_rules.json").read_text())
    mutation(raw)
    with pytest.raises(ValidationConfigError) as exc_info:
        parse_validation_config(json.dumps(raw))
    assert message in str(exc_info.value)
