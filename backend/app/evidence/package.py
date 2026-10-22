"""The evidence package: what one investigation is allowed to see.

Pure module (no database), shared by retrieval and the AI layer.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class EvidenceType(StrEnum):
    VALIDATION_FINDING = "VALIDATION_FINDING"
    UPSTREAM_RECORD = "UPSTREAM_RECORD"
    DOWNSTREAM_RECORD = "DOWNSTREAM_RECORD"
    MAPPING_RULE = "MAPPING_RULE"
    AGREEMENT_CLAUSE = "AGREEMENT_CLAUSE"
    HISTORICAL_CASE = "HISTORICAL_CASE"


class RetrievalMethod(StrEnum):
    EXCEPTION_SUBJECT = "EXCEPTION_SUBJECT"  # the finding under investigation
    EVALUATED_RECORD = "EVALUATED_RECORD"  # record version the rule evaluated
    SAME_LOAN_FINDING = "SAME_LOAN_FINDING"  # other active findings on the loan
    MAPPING_LOOKUP = "MAPPING_LOOKUP"  # recorded and active mapping rules
    CLAUSE_KEYWORD_MATCH = "CLAUSE_KEYWORD_MATCH"
    HISTORICAL_SIMILARITY = "HISTORICAL_SIMILARITY"


def content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PackagedEvidence:
    evidence_id: str
    evidence_type: str
    source_reference: str
    source_version: str | None
    loan_id: str | None
    retrieval_method: str
    relevance: str
    score: int | None
    content: dict[str, Any]


@dataclass(frozen=True)
class EvidencePackage:
    exception_id: str
    loan_id: str
    items: tuple[PackagedEvidence, ...]
    gaps: tuple[str, ...]

    def ids(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.items)

    def types_by_id(self) -> dict[str, str]:
        return {item.evidence_id: item.evidence_type for item in self.items}

    def descriptive_ids(self) -> frozenset[str]:
        """Evidence that shows *that* the values differ (the finding and the
        evaluated records) but cannot by itself explain *why*."""
        descriptive = {RetrievalMethod.EXCEPTION_SUBJECT.value, RetrievalMethod.EVALUATED_RECORD.value}
        return frozenset(i.evidence_id for i in self.items if i.retrieval_method in descriptive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "loan_id": self.loan_id,
            "items": [asdict(item) for item in self.items],
            "gaps": list(self.gaps),
        }
