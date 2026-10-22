"""Policy flags: warnings shown to the analyst, not rejections.

Wording is too varied to enforce reliably by pattern, so these heuristics
*flag* text that looks like it prescribes a change or declares a record
correct. The structural guarantees are elsewhere: the model has no tools,
no database access, and its output is advisory only.
"""

import re

from app.ai.schema import AiReportDraft

# Steps are imperative, so a step that *starts* with a change verb prescribes a change
# ("Update the Loan IQ product to REVOLVER"), while "Verify whether the product was changed" does not.
_CHANGE = re.compile(
    r"^\s*(please\s+)?(update|change|amend|correct|modify|rebook|re-book|overwrite|approve|override|set|book|fix)\b",
    re.IGNORECASE,
)
_VERDICT = re.compile(
    r"\b(upstream|downstream|ncino|loan ?iq)\b[^.]{0,40}\b(is|was|are)\s+(the\s+)?(correct|right|accurate|wrong|incorrect)\b",
    re.IGNORECASE,
)


def policy_flags(draft: AiReportDraft) -> list[str]:
    flags: list[str] = []
    for i, check in enumerate(draft.recommended_checks):
        if _CHANGE.search(check.step):
            flags.append(
                f"recommended_checks[{i}] appears to prescribe a change to banking data. "
                f"Any change requires analyst authorisation through the resolution workflow."
            )

    texts = [draft.summary, draft.overall_assessment, *(f.statement for f in draft.confirmed_facts)]
    texts += [c.reasoning for c in draft.probable_causes] + [c.cause for c in draft.probable_causes]
    if any(_VERDICT.search(t) for t in texts):
        flags.append(
            "The report appears to state which system's record is correct. Treat this as a hypothesis "
            "to verify, not a conclusion."
        )
    return flags
