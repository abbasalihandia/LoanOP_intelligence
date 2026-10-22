"""Pure relevance rules for clauses and historical cases."""

from app.evidence.relevance import HISTORY_MIN_SCORE, clause_keyword_matches, score_historical_case


def test_product_clause_matches_and_termination_clause_does_not():
    assert clause_keyword_matches(
        "product_type", "The Facility", "a US Dollar revolving credit facility in an aggregate amount"
    ) == ["revolving", "facility"]
    assert clause_keyword_matches("product_type", "Definitions - Termination Date", '"Termination Date" means 30 June 2030.') == []


def test_amendment_matches_amount():
    assert "reduced" in clause_keyword_matches("amount", "Reduction of Commitments", "Total Commitments are reduced")


def test_non_contractual_field_matches_nothing():
    assert clause_keyword_matches("mapping_version", "The Facility", "revolving facility") == []


def test_identical_case_scores_highest():
    score = score_historical_case(
        exc_category="PRODUCT_MISMATCH", exc_field="product_type", exc_source_value="Revolving Credit",
        exc_target_value="TERM", case_category="PRODUCT_MISMATCH", case_field="product_type",
        case_source_value="revolving credit", case_target_value="TERM",
    )
    assert score.score == 9 and len(score.reasons) == 4


def test_status_and_booking_status_are_the_same_field():
    score = score_historical_case(
        exc_category="BOOKING_FAILURE", exc_field="booking_status", exc_source_value="APPROVED",
        exc_target_value="FAILED", case_category="BOOKING_FAILURE", case_field="status",
        case_source_value="APPROVED", case_target_value="FAILED",
    )
    assert score.score == 9


def test_unrelated_case_below_threshold():
    score = score_historical_case(
        exc_category="CURRENCY_MISMATCH", exc_field="currency", exc_source_value="EUR", exc_target_value="USD",
        case_category="AMOUNT_MISMATCH", case_field="amount", case_source_value="1", case_target_value="2",
    )
    assert score.score < HISTORY_MIN_SCORE
