import psycopg2
import pytest

from opspilot.detection.detectors import Signal, detect
from opspilot.incidents.manager import auto_resolve_quiet, handle_signals
from opspilot.incidents.state_machine import IllegalTransition, Status, transition


@pytest.fixture()
def sid(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO services (name) VALUES ('target-app') RETURNING id")
        value = cur.fetchone()[0]
    conn.commit()
    return value


def sig(severity="SEV3", detector="error_rate", key=None, score=5.0):
    return Signal(detector, key or detector, severity, score, f"{detector} {severity}", {"x": 1})


def one(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_first_signal_opens_incident_and_repeats_attach(conn, sid):
    iid, created = handle_signals(conn, sid, [sig()])
    assert created
    iid2, created2 = handle_signals(conn, sid, [sig()])
    assert iid2 == iid and not created2
    assert one(conn, "SELECT count(*) FROM incidents") == 1
    assert one(conn, "SELECT hits FROM incident_signals WHERE incident_id = %s", iid) == 2


def test_no_signals_does_nothing(conn, sid):
    assert handle_signals(conn, sid, []) == (None, False)
    assert one(conn, "SELECT count(*) FROM incidents") == 0


def test_severity_only_goes_up_and_is_audited(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig("SEV3")])
    handle_signals(conn, sid, [sig("SEV1", "latency")])
    assert one(conn, "SELECT severity FROM incidents WHERE id = %s", iid) == "SEV1"
    handle_signals(conn, sid, [sig("SEV3")])
    assert one(conn, "SELECT severity FROM incidents WHERE id = %s", iid) == "SEV1"
    assert one(conn, "SELECT count(*) FROM incident_events WHERE reason LIKE 'severity raised%%'") == 1


def test_database_blocks_a_second_active_incident(conn, sid):
    handle_signals(conn, sid, [sig()])
    with conn.cursor() as cur, pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("INSERT INTO incidents (service_id, title, severity, detector) VALUES (%s, 'x', 'SEV3', 'x')", (sid,))
    conn.rollback()


def test_new_incident_allowed_after_resolution(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig()])
    transition(conn, iid, Status.RESOLVED, "test")
    iid2, created = handle_signals(conn, sid, [sig()])
    assert created and iid2 != iid


def test_full_happy_path_is_audited(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig()])
    for status in ["investigating", "awaiting_approval", "remediating", "verifying", "resolved"]:
        transition(conn, iid, status, f"to {status}", "test")
    assert one(conn, "SELECT status FROM incidents WHERE id = %s", iid) == "resolved"
    assert one(conn, "SELECT resolved_at IS NOT NULL FROM incidents WHERE id = %s", iid)
    assert one(conn, "SELECT count(*) FROM incident_events WHERE incident_id = %s", iid) == 6


def test_illegal_transition_is_rejected_and_changes_nothing(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig()])
    with pytest.raises(IllegalTransition):
        transition(conn, iid, Status.REMEDIATING, "skip approval")   # open -> remediating
    assert one(conn, "SELECT status FROM incidents WHERE id = %s", iid) == "open"
    assert one(conn, "SELECT count(*) FROM incident_events WHERE incident_id = %s", iid) == 1


def test_rejected_approval_goes_back_to_investigating(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig()])
    transition(conn, iid, Status.INVESTIGATING, "agent started")
    transition(conn, iid, Status.AWAITING_APPROVAL, "action proposed")
    transition(conn, iid, Status.INVESTIGATING, "approval rejected")
    assert one(conn, "SELECT status FROM incidents WHERE id = %s", iid) == "investigating"


def test_every_status_is_accepted_by_the_database(conn, sid):
    for i, status in enumerate(Status):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO services (name) VALUES (%s) RETURNING id", (f"svc{i}",))
            service = cur.fetchone()[0]
            cur.execute("INSERT INTO incidents (service_id, title, severity, detector, status) "
                        "VALUES (%s, 't', 'SEV3', 'd', %s)", (service, status.value))
    conn.commit()


def test_quiet_incident_resolves_but_remediating_one_does_not(conn, sid):
    iid, _ = handle_signals(conn, sid, [sig()])
    assert auto_resolve_quiet(conn, quiet_s=60) == []                    # signal is fresh
    with conn.cursor() as cur:
        cur.execute("UPDATE incidents SET last_signal_at = now() - interval '5 minutes'")
    conn.commit()
    assert auto_resolve_quiet(conn, quiet_s=60) == [iid]
    assert one(conn, "SELECT status FROM incidents WHERE id = %s", iid) == "resolved"

    iid2, _ = handle_signals(conn, sid, [sig()])
    for status in ["investigating", "awaiting_approval", "remediating"]:
        transition(conn, iid2, status, "x")
    with conn.cursor() as cur:
        cur.execute("UPDATE incidents SET last_signal_at = now() - interval '5 minutes' WHERE id = %s", (iid2,))
    conn.commit()
    assert auto_resolve_quiet(conn, quiet_s=60) == []
    assert one(conn, "SELECT status FROM incidents WHERE id = %s", iid2) == "remediating"


def seed_baseline(conn, sid):
    """20 healthy minutes of features and memory samples, ending 3 minutes ago."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO minute_features (service_id, minute, requests, errors, error_rate, p95_latency_ms)
               SELECT %s, date_trunc('minute', now()) - make_interval(mins => g), 580, 0, 0, 85
               FROM generate_series(3, 23) g""", (sid,))
        cur.execute(
            """INSERT INTO metric_points (service_id, metric, ts, value)
               SELECT %s, 'memory_mb', now() - make_interval(secs => g * 10), 80 FROM generate_series(10, 150) g""",
            (sid,))
    conn.commit()


def add_requests(conn, sid, healthy, failed, latency_ms=40):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO log_events (service_id, ts, level, message, attributes)
               SELECT %s, now() - make_interval(secs => mod(g, 25)),
                      CASE WHEN g <= %s THEN 'ERROR' ELSE 'INFO' END, 'm',
                      jsonb_build_object('status', CASE WHEN g <= %s THEN 500 ELSE 200 END, 'latency_ms', %s::float8)
               FROM generate_series(1, %s) g""",
            (sid, failed, failed, latency_ms, healthy + failed))
    conn.commit()


def test_detect_is_quiet_on_healthy_traffic(conn, sid):
    seed_baseline(conn, sid)
    add_requests(conn, sid, healthy=200, failed=0)
    assert detect(conn, sid) == []


def test_detect_flags_error_spike_with_severity(conn, sid):
    seed_baseline(conn, sid)
    add_requests(conn, sid, healthy=160, failed=40)               # 20% errors
    signals = detect(conn, sid)
    assert [s.detector for s in signals] == ["error_rate"]
    assert signals[0].severity == "SEV2"


def test_detect_flags_latency_and_memory(conn, sid):
    seed_baseline(conn, sid)
    add_requests(conn, sid, healthy=200, failed=0, latency_ms=3000)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO metric_points (service_id, metric, ts, value) VALUES (%s, 'memory_mb', now(), 190)", (sid,))
    conn.commit()
    assert {s.detector for s in detect(conn, sid)} == {"latency", "memory_growth"}
