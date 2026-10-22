"""Score one stored report against its scenario (pure).

Two kinds of output:
  checks   scenario-specific expectations; the scenario score is the share
           of applicable checks passed
  metrics  generic report-quality measures comparable across scenarios
           (citation accuracy, possibly-false "missing information",
           uncited mentions, high confidence despite contradicting evidence)
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.evaluation.scenarios import Scenario

SUFFICIENCY = {"SUFFICIENT": "SUFFICIENT_FOR_HYPOTHESIS", "INSUFFICIENT": "INSUFFICIENT"}
_NEGATION = re.compile(r"\b(not|no|isn't|is not|doesn't|does not|cannot|unlikely)\b", re.IGNORECASE)
# Identifiers worth tracking in free text: rule, clause, case, document, mapping version ids.
_IDENTIFIER_FIELDS = ("rule_id", "clause_id", "case_id", "document_ref", "mapping_version", "exception_id")


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool | None  # None = not applicable (e.g. expected evidence absent from the package)
    detail: str


@dataclass(frozen=True)
class ScoreResult:
    checks: list[Check]
    metrics: dict[str, Any]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"checks": [asdict(c) for c in self.checks], "metrics": self.metrics, "score": self.score}


def _items(package: dict[str, Any]) -> list[dict[str, Any]]:
    return list(package.get("items", []))


def evidence_id_for_key(package: dict[str, Any], key: str) -> str | None:
    """Evidence id whose source reference ends with `key` (e.g. MAP-PROD-V1-001)."""
    for item in _items(package):
        if str(item.get("source_reference", "")).split(":")[-1].upper() == key.upper():
            return str(item["evidence_id"])
    return None


def cited_evidence(report: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for fact in report.get("confirmed_facts", []):
        ids += fact.get("evidence_ids", [])
    for cause in report.get("probable_causes", []):
        ids += cause.get("supporting_evidence_ids", []) + cause.get("contradicting_evidence_ids", [])
    for alt in report.get("alternative_explanations", []):
        ids += alt.get("supporting_evidence_ids", [])
    for conflict in report.get("conflicting_evidence", []):
        ids += conflict.get("evidence_ids", [])
    for check in report.get("recommended_checks", []):
        ids += check.get("evidence_ids", [])
    return ids


def _cause_text(cause: dict[str, Any]) -> str:
    return f"{cause.get('cause', '')} {cause.get('reasoning', '')}".lower()


def _all_text(report: dict[str, Any]) -> str:
    parts = [report.get("summary", ""), report.get("overall_assessment", "")]
    parts += [f.get("statement", "") for f in report.get("confirmed_facts", [])]
    parts += [_cause_text(c) for c in report.get("probable_causes", [])]
    parts += [a.get("explanation", "") + " " + a.get("why_less_likely", "") for a in report.get("alternative_explanations", [])]
    parts += [c.get("description", "") for c in report.get("conflicting_evidence", [])]
    parts += [c.get("step", "") + " " + c.get("purpose", "") for c in report.get("recommended_checks", [])]
    parts += [m.get("item", "") + " " + m.get("why_needed", "") for m in report.get("missing_information", [])]
    parts += list(report.get("uncertainties", []))
    return " ".join(parts).lower()


def _identifiers(package: dict[str, Any]) -> dict[str, str]:
    """identifier (lowercase) -> evidence id, from evidence content."""
    found: dict[str, str] = {}
    for item in _items(package):
        content = item.get("content", {}) or {}
        for name in _IDENTIFIER_FIELDS:
            value = content.get(name)
            if isinstance(value, str) and len(value) >= 5:
                found.setdefault(value.lower(), str(item["evidence_id"]))
    return found


# --- Generic metrics -------------------------------------------------------------


def quality_metrics(report: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    package_ids = {str(i["evidence_id"]) for i in _items(package)}
    cited = cited_evidence(report)
    cited_set = set(cited)
    identifiers = _identifiers(package)
    text = _all_text(report)

    missing_items = [f"{m.get('item', '')} {m.get('why_needed', '')}".lower() for m in report.get("missing_information", [])]
    possibly_false_missing = [
        m for m in missing_items if any(ident in m for ident in identifiers) or any(eid.lower() in m for eid in package_ids)
    ]
    uncited_mentions = sorted({ident for ident, eid in identifiers.items() if ident in text and eid not in cited_set})
    causes = report.get("probable_causes", [])

    return {
        "citations": len(cited),
        "invalid_citations": sum(1 for e in cited if e not in package_ids),
        "distinct_evidence_cited": len(cited_set & package_ids),
        "evidence_in_package": len(package_ids),
        "probable_causes": len(causes),
        "evidence_supported_causes": sum(1 for c in causes if c.get("claim_type") == "EVIDENCE_SUPPORTED_HYPOTHESIS"),
        "high_confidence_with_contradiction": sum(
            1 for c in causes if c.get("confidence") == "high" and c.get("contradicting_evidence_ids")
        ),
        "possibly_false_missing_information": len(possibly_false_missing),
        "uncited_mentions": uncited_mentions,
        "policy_flags": len(report.get("policy_flags", [])),
        "escalation_recommended": bool(report.get("escalation", {}).get("recommended")),
        "evidence_sufficiency": report.get("evidence_sufficiency"),
    }


# --- Scenario checks ---------------------------------------------------------------


def score_report(scenario: Scenario, report: dict[str, Any] | None, package: dict[str, Any]) -> ScoreResult:
    if report is None:
        return ScoreResult([Check("valid_report", False, "No validated report was produced.")], {}, 0.0)

    checks: list[Check] = [Check("valid_report", True, "Report passed schema and evidence validation.")]
    cited = set(cited_evidence(report))
    causes = report.get("probable_causes", [])

    if scenario.expected_sufficiency:
        expected = SUFFICIENCY[scenario.expected_sufficiency]
        actual = report.get("evidence_sufficiency")
        checks.append(Check("evidence_sufficiency", actual == expected, f"expected {expected}, got {actual}"))

    if scenario.cause_keywords:
        match = next(
            (c for c in causes if all(any(k in _cause_text(c) for k in group) for group in scenario.cause_keywords)),
            None,
        )
        checks.append(Check(
            "expected_cause_found", match is not None,
            f"matched: {match.get('cause')!r}" if match else "no probable cause matched the expected cause",
        ))

    for key in scenario.must_cite:
        eid = evidence_id_for_key(package, key)
        if eid is None:
            checks.append(Check(f"cites {key}", None, f"{key} was not in the evidence package"))
        else:
            checks.append(Check(f"cites {key}", eid in cited, f"{key} = {eid} {'cited' if eid in cited else 'not cited'}"))

    for key in scenario.must_not_contradict:
        eid = evidence_id_for_key(package, key)
        if eid is None:
            checks.append(Check(f"does not treat {key} as contradicting", None, f"{key} not in package"))
            continue
        contradicting = any(eid in c.get("contradicting_evidence_ids", []) for c in causes)
        checks.append(Check(
            f"does not treat {key} as contradicting", not contradicting,
            f"{eid} {'was' if contradicting else 'was not'} cited as contradicting evidence",
        ))

    if scenario.expect_conflict:
        conflicts = report.get("conflicting_evidence", [])
        checks.append(Check("conflict_flagged", bool(conflicts), f"{len(conflicts)} conflict(s) recorded"))

    if scenario.missing_info_keywords:
        texts = [f"{m.get('item', '')} {m.get('why_needed', '')}".lower() for m in report.get("missing_information", [])]
        texts += [c.get("step", "").lower() for c in report.get("recommended_checks", []) if c.get("basis") == "MISSING_INFORMATION"]
        hit = next((t for t in texts if any(k in t for k in scenario.missing_info_keywords)), None)
        checks.append(Check("asks_for_missing_information", hit is not None,
                            f"matched: {hit!r}" if hit else "no missing-information item matched"))

    if scenario.mapping_must_not_be_blamed:
        rule_eid = evidence_id_for_key(package, scenario.mapping_must_not_be_blamed)
        blamed = [
            c for c in causes
            if c.get("claim_type") == "EVIDENCE_SUPPORTED_HYPOTHESIS"
            and c.get("confidence") in ("medium", "high")
            and "mapping" in _cause_text(c)
            and not _NEGATION.search(c.get("cause", ""))
            and (rule_eid is None or rule_eid in c.get("supporting_evidence_ids", []))
        ]
        checks.append(Check(
            "does_not_blame_correct_mapping", not blamed,
            f"blamed in: {blamed[0].get('cause')!r}" if blamed else "the correctly configured mapping was not blamed",
        ))

    if scenario.forbid_high_confidence:
        high = [c.get("cause") for c in causes if c.get("confidence") == "high"]
        checks.append(Check("no_high_confidence", not high, f"high-confidence causes: {high}" if high else "none"))

    applicable = [c for c in checks if c.passed is not None]
    score = round(sum(1 for c in applicable if c.passed) / len(applicable), 3) if applicable else 0.0
    return ScoreResult(checks, quality_metrics(report, package), score)
