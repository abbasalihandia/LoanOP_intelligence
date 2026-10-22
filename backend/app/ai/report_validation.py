"""Turn raw model text into a validated AiReportDraft, or explain why not.

Layer 1  JSON parsing (tolerates a ```json fence or a leading <think> block)
Layer 2  Pydantic structure (AiReportDraft and its validators)
Layer 3  Semantics against the evidence package:
           - exception_id matches
           - every cited evidence id was supplied
           - historical cases alone cannot support a hypothesis
           - the finding and evaluated records alone cannot support a
             hypothesis (they show that values differ, not why)
           - nor can they combined with historical cases: an evidence-
             supported hypothesis needs explanatory evidence for this loan
"""

import json
import re

from pydantic import ValidationError

from app.ai.schema import AiReportDraft
from app.evidence.package import EvidencePackage, EvidenceType

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class ReportValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _extract_json_text(raw: str) -> str:
    text = _THINK.sub("", raw).strip()
    fenced = _FENCE.match(text)
    return fenced.group(1) if fenced else text


def parse_report(raw: str, package: EvidencePackage, exception_id: str) -> AiReportDraft:
    text = _extract_json_text(raw)
    if not text:
        raise ReportValidationError(["Response was empty."])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportValidationError([f"Response is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."]) from exc
    if not isinstance(data, dict):
        raise ReportValidationError(["Response must be a single JSON object."])

    try:
        draft = AiReportDraft.model_validate(data)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err["loc"]) or "(root)"
            errors.append(f"{location}: {err['msg']}")
        raise ReportValidationError(errors) from exc

    errors: list[str] = []
    if draft.exception_id != exception_id:
        errors.append(f"exception_id must be '{exception_id}', got '{draft.exception_id}'.")

    known = package.ids()
    for location, evidence_id in draft.cited_evidence():
        if evidence_id not in known:
            errors.append(f"{location} cites {evidence_id}, which is not in the evidence package.")

    types = package.types_by_id()
    descriptive = package.descriptive_ids()
    downgraded: set[int] = set()  # causes that must become UNVERIFIED_POSSIBILITY unless better evidence is cited
    for i, cause in enumerate(draft.probable_causes):
        support = cause.supporting_evidence_ids
        if support and all(types.get(e) == EvidenceType.HISTORICAL_CASE for e in support):
            if cause.claim_type != "UNVERIFIED_POSSIBILITY" or cause.confidence != "low":
                downgraded.add(i)
                errors.append(
                    f"probable_causes[{i}] is supported only by historical cases, which are not proof of the "
                    f"current cause; it must be an UNVERIFIED_POSSIBILITY with low confidence."
                )
        elif (
            cause.claim_type == "EVIDENCE_SUPPORTED_HYPOTHESIS"
            and support
            and all(e in descriptive for e in support)
        ):
            downgraded.add(i)
            errors.append(
                f"probable_causes[{i}] cites only the finding and the evaluated records, which show that the "
                f"values differ but not why. Cite explanatory evidence (mapping rule, clause, related finding) "
                f"or mark it as an UNVERIFIED_POSSIBILITY."
            )
        elif (
            cause.claim_type == "EVIDENCE_SUPPORTED_HYPOTHESIS"
            and support
            and all(e in descriptive or types.get(e) == EvidenceType.HISTORICAL_CASE for e in support)
        ):
            # EVAL-00003 S08: finding + a historical case slipped past both rules above.
            downgraded.add(i)
            errors.append(
                f"probable_causes[{i}] cites only the finding, the evaluated records and historical cases. "
                f"Historical cases concern other loans and are not proof of the current cause. Cite explanatory "
                f"evidence for this loan (mapping rule, clause, related finding) or mark it as an "
                f"UNVERIFIED_POSSIBILITY."
            )

    # State the knock-on effect in the same feedback, so one corrective retry can
    # fix both: relabelling every supported cause as unverified would leave
    # SUFFICIENT_FOR_HYPOTHESIS invalid (see the schema rule).
    remaining_supported = [
        i for i, c in enumerate(draft.probable_causes)
        if c.claim_type == "EVIDENCE_SUPPORTED_HYPOTHESIS" and i not in downgraded
    ]
    if downgraded and not remaining_supported and draft.evidence_sufficiency == "SUFFICIENT_FOR_HYPOTHESIS":
        errors.append(
            "If you mark these causes as UNVERIFIED_POSSIBILITY instead of citing explanatory evidence, no "
            "EVIDENCE_SUPPORTED_HYPOTHESIS remains, so evidence_sufficiency must then be INSUFFICIENT."
        )

    if errors:
        raise ReportValidationError(errors)
    return draft
