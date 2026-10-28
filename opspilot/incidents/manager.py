"""Opens, updates and closes incidents from detector signals."""
import logging
import os

import psycopg2.extras

from opspilot.detection.detectors import Signal, severity_rank
from opspilot.incidents.state_machine import Status, transition

log = logging.getLogger("incidents")
QUIET_S = int(os.getenv("INCIDENT_QUIET_S", "120"))

ACTIVE_SQL = (
    "SELECT id, severity FROM incidents "
    "WHERE service_id = %s AND status NOT IN ('resolved', 'escalated') FOR UPDATE"
)


def handle_signals(conn, service_id: int, signals: list[Signal]) -> tuple[int | None, bool]:
    """Attach signals to the service's active incident, or open one. Returns (incident_id, created).

    One active incident per service is enforced by a unique index, so a repeated signal can
    never create a duplicate."""
    if not signals:
        return None, False
    top = max(signals, key=lambda s: (severity_rank(s.severity), s.score))
    created = False
    with conn.cursor() as cur:
        cur.execute(ACTIVE_SQL, (service_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO incidents (service_id, title, severity, detector) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (service_id, top.summary, top.severity, top.detector),
            )
            new = cur.fetchone()
            if new:
                incident_id, created = new[0], True
                cur.execute(
                    "INSERT INTO incident_events (incident_id, from_status, to_status, reason, actor) "
                    "VALUES (%s, NULL, 'open', %s, 'detector')",
                    (incident_id, f"detected: {top.summary}"),
                )
            else:  # another worker opened it a moment ago
                cur.execute(ACTIVE_SQL, (service_id,))
                incident_id, current_sev = cur.fetchone()
        else:
            incident_id, current_sev = row
            if severity_rank(top.severity) > severity_rank(current_sev):
                cur.execute("UPDATE incidents SET severity = %s WHERE id = %s", (top.severity, incident_id))
                cur.execute(
                    "INSERT INTO incident_events (incident_id, from_status, to_status, reason, actor) "
                    "SELECT id, status, status, %s, 'detector' FROM incidents WHERE id = %s",
                    (f"severity raised {current_sev} -> {top.severity}: {top.summary}", incident_id),
                )
        for s in signals:
            cur.execute(
                """INSERT INTO incident_signals
                     (incident_id, signal_key, detector, severity, score, summary, details, template_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (incident_id, signal_key) DO UPDATE SET
                     last_seen = now(), hits = incident_signals.hits + 1,
                     score = GREATEST(incident_signals.score, EXCLUDED.score),
                     severity = EXCLUDED.severity, summary = EXCLUDED.summary, details = EXCLUDED.details""",
                (incident_id, s.key, s.detector, s.severity, s.score, s.summary,
                 psycopg2.extras.Json(s.details), s.template_id),
            )
        cur.execute("UPDATE incidents SET last_signal_at = now() WHERE id = %s", (incident_id,))
    conn.commit()
    return incident_id, created


def auto_resolve_quiet(conn, quiet_s: int = QUIET_S) -> list[int]:
    """Close incidents that no detector has fired on for `quiet_s` seconds.

    Only states before remediation are touched. Once an action is running, the verifier
    owns the incident."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM incidents WHERE status IN ('open', 'investigating', 'awaiting_approval') "
            "AND last_signal_at < now() - make_interval(secs => %s)",
            (quiet_s,),
        )
        ids = [r[0] for r in cur.fetchall()]
    conn.commit()
    for incident_id in ids:
        transition(conn, incident_id, Status.RESOLVED, f"no anomaly signals for {quiet_s} seconds", "detector")
    return ids
