"""Exception lifecycle: the only place status transitions are defined.

                 ┌──────────────► ESCALATED ◄──────────────┐
                 │                    │                     │
  OPEN ──► UNDER_INVESTIGATION ◄──► AWAITING_EVIDENCE       │
   │             │   ▲                                      │
   │             ▼   │                                      │
   │     RECOMMENDATION_GENERATED  (AI service only) ───────┤
   │             │                                          │
   └──► REJECTED ◄┘   RESOLVED (resolution workflow only)   │

RESOLVED and REJECTED are terminal. A discrepancy that recurs with
different values after closure becomes a new exception.

Pure module: no database access.
"""

from enum import StrEnum


class ExceptionStatus(StrEnum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    RECOMMENDATION_GENERATED = "RECOMMENDATION_GENERATED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


S = ExceptionStatus

TERMINAL: frozenset[ExceptionStatus] = frozenset({S.RESOLVED, S.REJECTED})

ALLOWED_TRANSITIONS: dict[ExceptionStatus, frozenset[ExceptionStatus]] = {
    S.OPEN: frozenset({S.UNDER_INVESTIGATION, S.ESCALATED, S.REJECTED}),
    S.UNDER_INVESTIGATION: frozenset(
        {S.AWAITING_EVIDENCE, S.RECOMMENDATION_GENERATED, S.ESCALATED, S.RESOLVED, S.REJECTED}
    ),
    S.AWAITING_EVIDENCE: frozenset({S.UNDER_INVESTIGATION, S.ESCALATED, S.REJECTED}),
    S.RECOMMENDATION_GENERATED: frozenset({S.UNDER_INVESTIGATION, S.ESCALATED, S.RESOLVED, S.REJECTED}),
    S.ESCALATED: frozenset({S.UNDER_INVESTIGATION, S.RESOLVED, S.REJECTED}),
    S.RESOLVED: frozenset(),
    S.REJECTED: frozenset(),
}

# Targets that analysts cannot set directly through the status endpoint.
SYSTEM_ONLY_TARGETS: dict[ExceptionStatus, str] = {
    S.RECOMMENDATION_GENERATED: "is set only by the AI investigation service",
    S.RESOLVED: "is set only through the resolution workflow, which records the confirmed root cause",
}

REASON_REQUIRED: frozenset[ExceptionStatus] = frozenset({S.REJECTED, S.ESCALATED, S.AWAITING_EVIDENCE})

SYSTEM_ACTOR_PREFIX = "system:"


class TransitionError(ValueError):
    """The requested status change is not permitted."""


def check_transition(
    current: ExceptionStatus,
    target: ExceptionStatus,
    *,
    reason: str | None,
    via_system: bool = False,
) -> None:
    """Raise TransitionError unless current -> target is permitted."""
    if current == target:
        raise TransitionError(f"Exception is already {current.value}.")
    if current in TERMINAL:
        raise TransitionError(f"{current.value} is a terminal status; no further changes are allowed.")
    if target not in ALLOWED_TRANSITIONS[current]:
        allowed = ", ".join(sorted(s.value for s in ALLOWED_TRANSITIONS[current]))
        raise TransitionError(f"Cannot move from {current.value} to {target.value}. Allowed: {allowed}.")
    if target in SYSTEM_ONLY_TARGETS and not via_system:
        raise TransitionError(f"{target.value} {SYSTEM_ONLY_TARGETS[target]}.")
    if target in REASON_REQUIRED and not (reason and reason.strip()):
        raise TransitionError(f"A reason is required when moving to {target.value}.")


def analyst_next_statuses(current: ExceptionStatus) -> list[ExceptionStatus]:
    """Statuses an analyst may move to from `current` via the status endpoint."""
    return sorted(
        (s for s in ALLOWED_TRANSITIONS[current] if s not in SYSTEM_ONLY_TARGETS),
        key=lambda s: list(ExceptionStatus).index(s),
    )
