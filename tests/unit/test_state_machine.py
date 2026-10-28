import itertools

import pytest

from opspilot.incidents.state_machine import ALLOWED, TERMINAL, Status, can_transition

S = Status
LEGAL = [
    (S.OPEN, S.INVESTIGATING), (S.INVESTIGATING, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, S.REMEDIATING), (S.REMEDIATING, S.VERIFYING), (S.VERIFYING, S.RESOLVED),
    (S.AWAITING_APPROVAL, S.INVESTIGATING),   # approval rejected
    (S.AWAITING_APPROVAL, S.ESCALATED),       # approval timeout
    (S.REMEDIATING, S.ESCALATED),             # execution failed
    (S.VERIFYING, S.INVESTIGATING),           # fix did not work
    (S.VERIFYING, S.ESCALATED),               # inconclusive
    (S.OPEN, S.RESOLVED), (S.INVESTIGATING, S.RESOLVED), (S.AWAITING_APPROVAL, S.RESOLVED),  # recovered on its own
    (S.OPEN, S.ESCALATED), (S.INVESTIGATING, S.ESCALATED),  # investigation failed or timed out
]
ILLEGAL = [
    (S.OPEN, S.REMEDIATING), (S.OPEN, S.VERIFYING), (S.OPEN, S.AWAITING_APPROVAL),
    (S.INVESTIGATING, S.REMEDIATING), (S.REMEDIATING, S.RESOLVED), (S.REMEDIATING, S.INVESTIGATING),
    (S.RESOLVED, S.OPEN), (S.RESOLVED, S.INVESTIGATING), (S.ESCALATED, S.OPEN), (S.ESCALATED, S.RESOLVED),
]


@pytest.mark.parametrize("a,b", LEGAL)
def test_legal(a, b):
    assert can_transition(a, b)


@pytest.mark.parametrize("a,b", ILLEGAL)
def test_illegal(a, b):
    assert not can_transition(a, b)


def test_every_status_has_rules_and_terminals_are_final():
    assert set(ALLOWED) == set(Status)
    assert all(not ALLOWED[t] for t in TERMINAL)


def test_nothing_transitions_to_itself():
    assert not any(can_transition(s, s) for s in Status)


def test_no_unlisted_pairs_are_allowed():
    allowed = {(a, b) for a, b in itertools.product(Status, Status) if can_transition(a, b)}
    assert allowed == set(LEGAL)
