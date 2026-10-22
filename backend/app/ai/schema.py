"""AI report schemas.

AiReportDraft      what the model must return (validated structurally here,
                   then semantically against the evidence package in
                   report_validation.py)
AiInvestigationReport
                   what the platform stores and shows: the draft plus
                   deterministic facts (observed discrepancies), standard
                   statements, policy flags and provenance.
"""

from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EvidenceId = Annotated[str, StringConstraints(pattern=r"^EV-\d{5}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Confidence = Literal["low", "medium", "high"]

INSUFFICIENT_STATEMENT = "The root cause cannot be established from the available information."
HYPOTHESIS_STATEMENT = (
    "Probable causes below are hypotheses for analyst verification. None is a confirmed root cause."
)
CONFIDENCE_NOTE = (
    "Confidence levels (low/medium/high) are the model's qualitative judgement. "
    "They are not calibrated probabilities."
)
DISCLAIMER = "AI-generated recommendation. Not a confirmed finding. All decisions rest with the analyst."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmedFact(_Strict):
    statement: ShortText = Field(description="A fact directly shown by the cited evidence.")
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=10)


class ProbableCause(_Strict):
    cause: ShortText
    claim_type: Literal["EVIDENCE_SUPPORTED_HYPOTHESIS", "UNVERIFIED_POSSIBILITY"]
    supporting_evidence_ids: list[EvidenceId] = Field(max_length=10)
    contradicting_evidence_ids: list[EvidenceId] = Field(max_length=10)
    reasoning: Text
    confidence: Confidence = Field(description="Qualitative judgement only; not a probability.")

    @model_validator(mode="after")
    def _check(self) -> "ProbableCause":
        if self.claim_type == "EVIDENCE_SUPPORTED_HYPOTHESIS" and not self.supporting_evidence_ids:
            raise ValueError("an EVIDENCE_SUPPORTED_HYPOTHESIS must cite at least one supporting evidence id")
        overlap = set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids)
        if overlap:
            raise ValueError(f"evidence ids cannot both support and contradict a cause: {sorted(overlap)}")
        return self


class AlternativeExplanation(_Strict):
    explanation: ShortText
    supporting_evidence_ids: list[EvidenceId] = Field(max_length=10)
    why_less_likely: ShortText


class EvidenceConflict(_Strict):
    description: ShortText
    evidence_ids: list[EvidenceId] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def _distinct(self) -> "EvidenceConflict":
        if len(set(self.evidence_ids)) < 2:
            raise ValueError("a conflict must involve at least two different evidence ids")
        return self


class RecommendedCheck(_Strict):
    step: ShortText = Field(description="An investigation step. Never an instruction to change records.")
    purpose: ShortText
    basis: Literal["EVIDENCE", "MISSING_INFORMATION"]
    evidence_ids: list[EvidenceId] = Field(max_length=10)

    @model_validator(mode="after")
    def _check(self) -> "RecommendedCheck":
        if self.basis == "EVIDENCE" and not self.evidence_ids:
            raise ValueError("a check with basis EVIDENCE must cite at least one evidence id")
        return self


class MissingInformation(_Strict):
    item: ShortText
    why_needed: ShortText


class Escalation(_Strict):
    recommended: bool
    reason: ShortText


class AiReportDraft(_Strict):
    """The JSON object the model must produce."""

    exception_id: str
    summary: Text
    evidence_sufficiency: Literal["SUFFICIENT_FOR_HYPOTHESIS", "INSUFFICIENT"]
    confirmed_facts: list[ConfirmedFact] = Field(max_length=15)
    probable_causes: list[ProbableCause] = Field(max_length=6)
    alternative_explanations: list[AlternativeExplanation] = Field(max_length=6)
    conflicting_evidence: list[EvidenceConflict] = Field(max_length=6)
    recommended_checks: list[RecommendedCheck] = Field(min_length=1, max_length=10)
    missing_information: list[MissingInformation] = Field(max_length=10)
    uncertainties: list[ShortText] = Field(max_length=10)
    escalation: Escalation
    overall_assessment: Text

    @model_validator(mode="after")
    def _consistency(self) -> "AiReportDraft":
        # SUFFICIENT_FOR_HYPOTHESIS means the evidence supports at least one
        # hypothesis. Unverified possibilities alone do not meet that bar
        # (observed in EVAL-00002 S04/S06/S08: "sufficient" with only
        # unverified causes, one of them stating the root cause cannot be
        # established).
        if self.evidence_sufficiency == "SUFFICIENT_FOR_HYPOTHESIS" and not any(
            c.claim_type == "EVIDENCE_SUPPORTED_HYPOTHESIS" for c in self.probable_causes
        ):
            raise ValueError(
                "evidence_sufficiency SUFFICIENT_FOR_HYPOTHESIS requires at least one EVIDENCE_SUPPORTED_HYPOTHESIS; "
                "with no causes or only UNVERIFIED_POSSIBILITY causes, set evidence_sufficiency to INSUFFICIENT"
            )
        if self.evidence_sufficiency == "INSUFFICIENT" and any(c.confidence == "high" for c in self.probable_causes):
            raise ValueError("when evidence is INSUFFICIENT, no probable cause may have high confidence")
        return self

    def cited_evidence(self) -> list[tuple[str, str]]:
        """(location, evidence_id) for every citation in the report."""
        cited: list[tuple[str, str]] = []
        for i, fact in enumerate(self.confirmed_facts):
            cited += [(f"confirmed_facts[{i}]", e) for e in fact.evidence_ids]
        for i, cause in enumerate(self.probable_causes):
            cited += [(f"probable_causes[{i}].supporting", e) for e in cause.supporting_evidence_ids]
            cited += [(f"probable_causes[{i}].contradicting", e) for e in cause.contradicting_evidence_ids]
        for i, alt in enumerate(self.alternative_explanations):
            cited += [(f"alternative_explanations[{i}]", e) for e in alt.supporting_evidence_ids]
        for i, conflict in enumerate(self.conflicting_evidence):
            cited += [(f"conflicting_evidence[{i}]", e) for e in conflict.evidence_ids]
        for i, check in enumerate(self.recommended_checks):
            cited += [(f"recommended_checks[{i}]", e) for e in check.evidence_ids]
        return cited


# --- Stored report -------------------------------------------------------------


class ObservedDiscrepancy(BaseModel):
    field: str | None
    upstream_value: str | None
    downstream_value: str | None
    validation_rule_id: str
    explanation: str
    source: Literal["DETERMINISTIC_VALIDATION"] = "DETERMINISTIC_VALIDATION"


class AiInvestigationReport(BaseModel):
    report_type: Literal["AI_GENERATED_RECOMMENDATION"] = "AI_GENERATED_RECOMMENDATION"
    disclaimer: str = DISCLAIMER
    exception_id: str
    summary: str
    observed_discrepancies: list[ObservedDiscrepancy]
    evidence_sufficiency: str
    root_cause_statement: str
    confirmed_facts: list[ConfirmedFact]
    probable_causes: list[ProbableCause]
    alternative_explanations: list[AlternativeExplanation]
    conflicting_evidence: list[EvidenceConflict]
    recommended_checks: list[RecommendedCheck]
    missing_information: list[MissingInformation]
    uncertainties: list[str]
    escalation: Escalation
    overall_assessment: str
    confidence_note: str = CONFIDENCE_NOTE
    policy_flags: list[str]
    evidence_package_ids: list[str]
    model: str
    generated_at: str


# --- Schema for Ollama's `format` parameter --------------------------------------


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            return _inline_refs(deepcopy(defs[name]), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def ollama_format_schema() -> dict[str, Any]:
    """JSON schema for AiReportDraft with $refs inlined (simplest for grammar-constrained decoding)."""
    schema = AiReportDraft.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))
