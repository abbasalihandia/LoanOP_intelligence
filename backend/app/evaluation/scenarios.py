"""What a good investigation report looks like for each seeded scenario.

Expectations encode the synthetic ground truth designed in Phase 1 (see the
scenario catalogue in docs/PROJECT_LOG.md). They test behaviour that matters
to an analyst, not wording: e.g. LN-1003 must surface the amendment and must
not treat the upstream record as correct; LN-1010 must not blame a mapping
rule that maps correctly.

Keyword checks are deliberately simple and lenient; they are a screening
aid, not a substitute for analyst review of the stored reports.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    loan_id: str
    rule_id: str
    title: str
    good_report: str  # plain-language statement of the expected behaviour
    expected_sufficiency: str | None = None  # "SUFFICIENT" | "INSUFFICIENT" | None (either)
    # The expected cause is "found" if one probable cause's text matches every
    # group (each group: any of its keywords).
    cause_keywords: tuple[tuple[str, ...], ...] = ()
    must_cite: tuple[str, ...] = ()  # source keys (e.g. MAP-PROD-V1-001) that should be cited
    must_not_contradict: tuple[str, ...] = ()  # keys that must not be cited as contradicting
    expect_conflict: bool = False
    missing_info_keywords: tuple[str, ...] = ()
    mapping_must_not_be_blamed: str | None = None  # mapping rule key that maps correctly
    forbid_high_confidence: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "S01", "LN-1001", "RULE-PRODUCT-001", "Product mismatch caused by a retired mapping",
        "Identifies the retired PRODMAP-v1 rule (Revolving Credit to TERM) as a probable cause and cites it.",
        expected_sufficiency="SUFFICIENT",
        cause_keywords=(("mapping",), ("v1", "retired", "outdated", "old", "previous")),
        must_cite=("MAP-PROD-V1-001",),
        tags=("mapping supports cause",),
    ),
    Scenario(
        "S02", "LN-1001", "RULE-MAP-002", "Retired mapping produces a different result",
        "Explains that v1 maps to TERM while the active v2 maps to REVOLVER; v2 corroborates, it does not contradict.",
        expected_sufficiency="SUFFICIENT",
        cause_keywords=(("mapping", "prodmap"), ("v1", "retired", "outdated", "old", "previous")),
        must_cite=("MAP-PROD-V1-001", "MAP-PROD-V2-001"),
        must_not_contradict=("MAP-PROD-V2-001",),
        tags=("mapping supports cause",),
    ),
    Scenario(
        "S03", "LN-1003", "RULE-AMT-001", "Amount mismatch after a commitment reduction",
        "Surfaces the amendment reducing commitments to 20m, flags the conflict with the original agreement and "
        "the upstream record, and does not assume the upstream record is correct.",
        expected_sufficiency="SUFFICIENT",
        cause_keywords=(("amendment", "reduc", "not updated", "stale", "outdated"),),
        must_cite=("CL-AMD1003-01-3",),
        expect_conflict=True,
        tags=("conflicting evidence", "upstream is the stale side"),
    ),
    Scenario(
        "S04", "LN-1004", "RULE-CCY-001", "Currency mismatch with no contractual evidence",
        "States that the root cause cannot be established and asks for the facility agreement.",
        expected_sufficiency="INSUFFICIENT",
        missing_info_keywords=("agreement", "contract", "document", "facility terms"),
        forbid_high_confidence=True,
        tags=("missing contractual evidence", "insufficient evidence"),
    ),
    Scenario(
        "S05", "LN-1005", "RULE-MAT-001", "Maturity keyed incorrectly downstream",
        "Uses the Termination Date clause (31 Dec 2029) and proposes a keying/entry error as a hypothesis.",
        expected_sufficiency="SUFFICIENT",
        cause_keywords=(("keying", "keyed", "manual", "entry", "typo", "input", "data entry", "booking error"),),
        must_cite=("CL-FA1005-1.1",),
    ),
    Scenario(
        "S06", "LN-1006", "RULE-REQ-001", "Upstream maturity missing; date depends on utilisation",
        "Cites the clause defining maturity as 12 months after first utilisation and asks for the utilisation date.",
        must_cite=("CL-FA1006-1.1",),
        missing_info_keywords=("utilisation", "utilization", "drawdown", "draw down", "first draw"),
        tags=("missing information",),
    ),
    Scenario(
        "S07", "LN-1007", "RULE-BOOK-001", "Booking failed: pricing option not configured",
        "Links the SORA-3M pricing error to the interest clause and points to servicing static-data set-up.",
        expected_sufficiency="SUFFICIENT",
        cause_keywords=(("pricing", "sora", "static data", "configur", "set up", "setup"),),
        must_cite=("CL-FA1007-8.2",),
    ),
    Scenario(
        "S08", "LN-1008", "RULE-BOOK-002", "Approved loan never booked downstream",
        "Recognises there is no evidence of why booking did not happen and asks for interface/booking logs.",
        expected_sufficiency="INSUFFICIENT",
        missing_info_keywords=("log", "interface", "booking", "queue", "transmission", "status"),
        forbid_high_confidence=True,
        tags=("insufficient evidence",),
    ),
    Scenario(
        "S09", "LN-1009", "RULE-TYPE-001", "Unparseable downstream amount",
        "Identifies the malformed value (letter O instead of zero) as a likely entry error, without overclaiming.",
        cause_keywords=(("keying", "typo", "entry", "letter", "character", "format", "input", "invalid"),),
        forbid_high_confidence=True,
    ),
    Scenario(
        "S10", "LN-1010", "RULE-PRODUCT-001", "Product mismatch the mapping does not explain",
        "Recognises that active PRODMAP-v2 maps Bridge Loan to BRIDGE, so the mapping is not the cause.",
        must_cite=("MAP-PROD-V2-003",),
        mapping_must_not_be_blamed="MAP-PROD-V2-003",
        tags=("mapping does not explain",),
    ),
    Scenario(
        "S11", "LN-1010", "RULE-MAP-001", "Mapping not applied as configured",
        "Recognises the booked TERM contradicts the configured mapping and looks for a manual override or other cause.",
        must_cite=("MAP-PROD-V2-003",),
        mapping_must_not_be_blamed="MAP-PROD-V2-003",
        cause_keywords=(("manual", "override", "overrid", "changed", "edited", "amended", "not applied", "bypass"),),
        tags=("mapping does not explain",),
    ),
)


def scenario_by_id(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id.upper():
            return scenario
    raise KeyError(scenario_id)
