"""Pure status-transition tests."""

import pytest

from app.exception_engine.status import (
    ALLOWED_TRANSITIONS,
    TERMINAL,
    ExceptionStatus as S,
    TransitionError,
    analyst_next_statuses,
    check_transition,
)


def test_every_status_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_terminal_statuses_have_no_exits():
    for status in TERMINAL:
        assert ALLOWED_TRANSITIONS[status] == frozenset()


def test_normal_investigation_path():
    check_transition(S.OPEN, S.UNDER_INVESTIGATION, reason=None)
    check_transition(S.UNDER_INVESTIGATION, S.AWAITING_EVIDENCE, reason="Need executed amendment")
    check_transition(S.AWAITING_EVIDENCE, S.UNDER_INVESTIGATION, reason=None)


@pytest.mark.parametrize(
    "current, target, reason, via_system, fragment",
    [
        (S.OPEN, S.OPEN, None, False, "already"),
        (S.OPEN, S.AWAITING_EVIDENCE, "x", False, "Cannot move"),
        (S.OPEN, S.RESOLVED, None, False, "Cannot move"),
        (S.UNDER_INVESTIGATION, S.RESOLVED, None, False, "resolution workflow"),
        (S.UNDER_INVESTIGATION, S.RECOMMENDATION_GENERATED, None, False, "AI investigation service"),
        (S.OPEN, S.REJECTED, None, False, "reason is required"),
        (S.OPEN, S.ESCALATED, "   ", False, "reason is required"),
        (S.RESOLVED, S.UNDER_INVESTIGATION, None, True, "terminal"),
        (S.REJECTED, S.OPEN, None, True, "terminal"),
    ],
)
def test_forbidden_transitions(current, target, reason, via_system, fragment):
    with pytest.raises(TransitionError) as exc_info:
        check_transition(current, target, reason=reason, via_system=via_system)
    assert fragment in str(exc_info.value)


def test_system_may_set_system_only_statuses():
    check_transition(S.UNDER_INVESTIGATION, S.RECOMMENDATION_GENERATED, reason=None, via_system=True)
    check_transition(S.RECOMMENDATION_GENERATED, S.RESOLVED, reason=None, via_system=True)


def test_analyst_options_exclude_system_only_targets():
    assert analyst_next_statuses(S.UNDER_INVESTIGATION) == [
        S.AWAITING_EVIDENCE, S.REJECTED, S.ESCALATED,
    ]
    assert analyst_next_statuses(S.RESOLVED) == []
