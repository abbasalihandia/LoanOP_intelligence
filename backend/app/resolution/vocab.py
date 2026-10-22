"""Controlled vocabularies for analyst resolutions (pure).

Each value has a human label so the UI never has to duplicate them.
"""

from enum import StrEnum


class AnalystDecision(StrEnum):
    AI_ACCEPTED = "AI_ACCEPTED"
    AI_MODIFIED = "AI_MODIFIED"
    AI_REJECTED = "AI_REJECTED"
    NO_AI_REPORT = "NO_AI_REPORT"


class RootCauseCategory(StrEnum):
    MAPPING_DEFECT = "MAPPING_DEFECT"
    OUTDATED_MAPPING_APPLIED = "OUTDATED_MAPPING_APPLIED"
    MANUAL_KEYING_ERROR = "MANUAL_KEYING_ERROR"
    UPSTREAM_NOT_UPDATED = "UPSTREAM_NOT_UPDATED"
    DOWNSTREAM_NOT_UPDATED = "DOWNSTREAM_NOT_UPDATED"
    STATIC_DATA_GAP = "STATIC_DATA_GAP"
    INTERFACE_FAILURE = "INTERFACE_FAILURE"
    SOURCE_DATA_QUALITY = "SOURCE_DATA_QUALITY"
    LEGITIMATE_DIFFERENCE = "LEGITIMATE_DIFFERENCE"
    OTHER = "OTHER"


class RecordInError(StrEnum):
    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"
    BOTH = "BOTH"
    NEITHER = "NEITHER"
    UNDETERMINED = "UNDETERMINED"


class ResolutionOutcome(StrEnum):
    CORRECTED_IN_SOURCE = "CORRECTED_IN_SOURCE"
    NO_CHANGE_REQUIRED = "NO_CHANGE_REQUIRED"
    REFERRED_TO_OWNER = "REFERRED_TO_OWNER"


LABELS: dict[str, dict[str, str]] = {
    "analyst_decision": {
        AnalystDecision.AI_ACCEPTED: "Accepted the AI's probable cause",
        AnalystDecision.AI_MODIFIED: "Modified the AI's probable cause",
        AnalystDecision.AI_REJECTED: "Rejected the AI recommendation",
        AnalystDecision.NO_AI_REPORT: "Resolved without an AI report",
    },
    "root_cause_category": {
        RootCauseCategory.MAPPING_DEFECT: "Mapping configuration defect",
        RootCauseCategory.OUTDATED_MAPPING_APPLIED: "Outdated mapping version applied",
        RootCauseCategory.MANUAL_KEYING_ERROR: "Manual keying error",
        RootCauseCategory.UPSTREAM_NOT_UPDATED: "Upstream record not updated",
        RootCauseCategory.DOWNSTREAM_NOT_UPDATED: "Downstream record not updated",
        RootCauseCategory.STATIC_DATA_GAP: "Static / reference data gap",
        RootCauseCategory.INTERFACE_FAILURE: "Interface or processing failure",
        RootCauseCategory.SOURCE_DATA_QUALITY: "Source data quality issue",
        RootCauseCategory.LEGITIMATE_DIFFERENCE: "Legitimate difference (not a defect)",
        RootCauseCategory.OTHER: "Other",
    },
    "record_in_error": {
        RecordInError.UPSTREAM: "Upstream record",
        RecordInError.DOWNSTREAM: "Downstream record",
        RecordInError.BOTH: "Both records",
        RecordInError.NEITHER: "Neither record",
        RecordInError.UNDETERMINED: "Could not be determined",
    },
    "outcome": {
        ResolutionOutcome.CORRECTED_IN_SOURCE: "Correction made in the source system",
        ResolutionOutcome.NO_CHANGE_REQUIRED: "No change required",
        ResolutionOutcome.REFERRED_TO_OWNER: "Referred to the owning team",
    },
}
