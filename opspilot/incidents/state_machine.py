"""Incident life cycle. Every status change goes through `transition()`, which checks the
rules below inside the database transaction and writes an audit row.

  open -> investigating -> awaiting_approval -> remediating -> verifying -> resolved

Side paths:
  awaiting_approval -> investigating   approval rejected, investigate again
  awaiting_approval -> escalated       nobody approved in time
  remediating       -> escalated       the action failed to run
  verifying         -> investigating   fix did not work
  verifying         -> escalated       verification inconclusive
  open / investigating / awaiting_approval -> resolved   recovered by itself (no signals for a while)
  open / investigating -> escalated    investigation failed or timed out
"""
from enum import Enum


class Status(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATING = "remediating"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


S = Status
ALLOWED: dict[Status, set[Status]] = {
    S.OPEN: {S.INVESTIGATING, S.RESOLVED, S.ESCALATED},
    S.INVESTIGATING: {S.AWAITING_APPROVAL, S.RESOLVED, S.ESCALATED},
    S.AWAITING_APPROVAL: {S.REMEDIATING, S.INVESTIGATING, S.ESCALATED, S.RESOLVED},
    S.REMEDIATING: {S.VERIFYING, S.ESCALATED},
    S.VERIFYING: {S.RESOLVED, S.INVESTIGATING, S.ESCALATED},
    S.RESOLVED: set(),
    S.ESCALATED: set(),
}
TERMINAL = {S.RESOLVED, S.ESCALATED}


class IllegalTransition(Exception):
    pass


def can_transition(current: Status, target: Status) -> bool:
    return target in ALLOWED[current]


def transition(conn, incident_id: int, target: Status | str, reason: str, actor: str = "system") -> None:
    """Move an incident to a new status. Raises IllegalTransition if the move is not allowed."""
    target = Status(target)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM incidents WHERE id = %s FOR UPDATE", (incident_id,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise LookupError(f"incident {incident_id} not found")
        current = Status(row[0])
        if not can_transition(current, target):
            conn.rollback()
            raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")
        cur.execute(
            "UPDATE incidents SET status = %s, "
            "resolved_at = CASE WHEN %s = 'resolved' THEN now() ELSE resolved_at END WHERE id = %s",
            (target.value, target.value, incident_id),
        )
        cur.execute(
            "INSERT INTO incident_events (incident_id, from_status, to_status, reason, actor) "
            "VALUES (%s, %s, %s, %s, %s)",
            (incident_id, current.value, target.value, reason, actor),
        )
    conn.commit()
