"""Deterministic relevance rules for clauses and historical cases (pure).

Simple and explainable on purpose: keyword matching for clauses, additive
attribute scoring for historical cases. No embeddings or vector store; the
reasons for every match are returned so analysts can see why it was chosen.
"""

from dataclasses import dataclass

# Exception field -> lowercase keywords that make a clause relevant.
FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "product_type": ("revolving", "term loan", "bridge", "letter of credit", "facility"),
    "amount": ("commitment", "aggregate amount", "amount equal", "reduced", "reduction"),
    "currency": ("currency", "us dollar", "euro", "sterling", "singapore dollar"),
    "maturity_date": ("termination date", "maturity", "final repayment"),
    "booking_status": ("interest", "pricing", "rate", "sora", "sofr", "margin"),
}

# Field names that refer to the same concept across sources.
_FIELD_ALIASES = {"status": "booking_status"}

HISTORY_MIN_SCORE = 4
HISTORY_MAX_RESULTS = 3


def clause_keyword_matches(field_name: str | None, title: str, text: str) -> list[str]:
    """Keywords for `field_name` that appear in the clause (empty if irrelevant)."""
    keywords = FIELD_KEYWORDS.get(field_name or "", ())
    haystack = f"{title} {text}".lower()
    return [k for k in keywords if k in haystack]


def is_contractual_field(field_name: str | None) -> bool:
    return (field_name or "") in FIELD_KEYWORDS


def _norm_field(name: str | None) -> str:
    value = (name or "").strip().lower()
    return _FIELD_ALIASES.get(value, value)


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


@dataclass(frozen=True)
class SimilarityScore:
    score: int
    reasons: tuple[str, ...]


def score_historical_case(
    *,
    exc_category: str,
    exc_field: str | None,
    exc_source_value: str | None,
    exc_target_value: str | None,
    case_category: str,
    case_field: str | None,
    case_source_value: str | None,
    case_target_value: str | None,
) -> SimilarityScore:
    score, reasons = 0, []
    if exc_category == case_category:
        score += 3
        reasons.append(f"same category ({case_category})")
    if exc_field and _norm_field(exc_field) == _norm_field(case_field):
        score += 2
        reasons.append(f"same field ({exc_field})")
    if _same(exc_source_value, case_source_value):
        score += 2
        reasons.append(f"same upstream value ({case_source_value})")
    if _same(exc_target_value, case_target_value):
        score += 2
        reasons.append(f"same downstream value ({case_target_value})")
    return SimilarityScore(score, tuple(reasons))
