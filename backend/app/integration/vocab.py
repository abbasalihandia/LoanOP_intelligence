"""Controlled vocabularies shared across the integration layer.

The canonical product vocabulary is how *this platform* compares records.
It is deliberately separate from the MappingRule table, which models the
bank's own interface configuration (the thing under investigation when a
mismatch occurs).
"""

from enum import StrEnum


class SourceSystem(StrEnum):
    """Simulated systems. The _SIM suffix marks them as synthetic."""

    NCINO_SIM = "NCINO_SIM"  # upstream origination (nCino-style)
    LOANIQ_SIM = "LOANIQ_SIM"  # downstream servicing (Finastra Loan IQ-style)


UPSTREAM = SourceSystem.NCINO_SIM
DOWNSTREAM = SourceSystem.LOANIQ_SIM


class ProductType(StrEnum):
    REVOLVING_CREDIT = "REVOLVING_CREDIT"
    TERM_LOAN = "TERM_LOAN"
    BRIDGE_LOAN = "BRIDGE_LOAN"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"


# Upstream product names (matched case-insensitively).
NCINO_PRODUCT_NAMES: dict[str, ProductType] = {
    "revolving credit": ProductType.REVOLVING_CREDIT,
    "term loan": ProductType.TERM_LOAN,
    "bridge loan": ProductType.BRIDGE_LOAN,
    "letter of credit": ProductType.LETTER_OF_CREDIT,
}

# Downstream product codes (matched case-insensitively).
LOANIQ_PRODUCT_CODES: dict[str, ProductType] = {
    "REVOLVER": ProductType.REVOLVING_CREDIT,
    "TERM": ProductType.TERM_LOAN,
    "BRIDGE": ProductType.BRIDGE_LOAN,
    "SBLC": ProductType.LETTER_OF_CREDIT,
}


class IngestionOutcome(StrEnum):
    CREATED = "CREATED"  # new version stored
    UNCHANGED = "UNCHANGED"  # identical to the current version
    STALE = "STALE"  # older than the current version; ignored
    REJECTED = "REJECTED"  # structurally unusable payload
