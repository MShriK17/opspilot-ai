import json
from datetime import datetime, timedelta, timezone

import psycopg2.extras
import pytest

from opspilot.processing.drain_parser import MinerPool, process_templates
from opspilot.processing.features import compute_features

BASE = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(second=0, microsecond=0)


def add_logs(conn, rows):
    """rows: (minute_offset, second, level, message, status, latency_ms)"""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO services (name) VALUES ('target-app') ON CONFLICT DO NOTHING")
        cur.execute("SELECT id FROM services WHERE name = 'target-app'")
        sid = cur.fetchone()[0]
        values = []
        for minute, sec, level, msg, status, lat in rows:
            attrs = {"version": "v2.0.0" if minute >= 2 else "v1.0.0"}
            if status:
                attrs.update({"status": status, "latency_ms": lat})
            values.append((sid, BASE + timedelta(minutes=minute, seconds=sec), level, msg, json.dumps(attrs)))
        psycopg2.extras.execute_values(
            cur, "INSERT INTO log_events (service_id, ts, level, message, attributes) VALUES %s", values,
            template="(%s, %s, %s, %s, %s::jsonb)",
        )
    conn.commit()
    return sid


def scenario_rows():
    rows = []
    for minute in range(4):
        for i in range(10):  # 10 healthy requests every minute
            rows.append((minute, i, "INFO", "request completed", 200, 20.0 + i))
    for i in range(4):  # minute 2: 4 failures from a brand-new error
        rows.append((2, 30 + i, "ERROR", "TypeError: 'NoneType' object is not subscriptable", 500, 30.0))
    return rows


def test_templates_assigned_and_features_computed(conn, tmp_path):
    sid = add_logs(conn, scenario_rows())
    assert process_templates(conn, MinerPool(str(tmp_path))) == 44
    compute_features(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM log_events WHERE template_id IS NULL")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM log_templates WHERE service_id = %s", (sid,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT requests, errors, error_rate, error_templates, new_templates, version "
                    "FROM minute_features WHERE minute = %s", (BASE + timedelta(minutes=2),))
        requests, errors, rate, err_templates, new_templates, version = cur.fetchone()
    assert (requests, errors, err_templates, new_templates) == (14, 4, 1, 1)
    assert rate == pytest.approx(4 / 14)
    assert version == "v2.0.0"


def test_healthy_minute_has_zero_errors(conn, tmp_path):
    add_logs(conn, scenario_rows())
    process_templates(conn, MinerPool(str(tmp_path)))
    compute_features(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT requests, errors, error_templates FROM minute_features WHERE minute = %s",
                    (BASE + timedelta(minutes=1),))
        assert cur.fetchone() == (10, 0, 0)


def test_rerunning_is_idempotent(conn, tmp_path):
    add_logs(conn, scenario_rows())
    pool = MinerPool(str(tmp_path))
    process_templates(conn, pool)
    compute_features(conn)
    snapshot = []
    for _ in range(2):
        assert process_templates(conn, pool) == 0
        compute_features(conn, full=True)
        with conn.cursor() as cur:
            cur.execute("SELECT sum(requests), sum(errors) FROM minute_features")
            a = cur.fetchone()
            cur.execute("SELECT sum(event_count) FROM template_minute_counts")
            snapshot.append((a, cur.fetchone()))
    assert snapshot[0] == snapshot[1]
    assert snapshot[0][0] == (44, 4)  # 40 healthy + 4 failed requests, 4 errors


def test_same_error_in_later_batch_reuses_template(conn, tmp_path):
    pool = MinerPool(str(tmp_path))
    add_logs(conn, [(0, 1, "ERROR", "payment-gateway timed out after 3.0s", 500, 3000.0)])
    process_templates(conn, pool)
    add_logs(conn, [(1, 1, "ERROR", "payment-gateway timed out after 2.5s", 500, 3000.0)])
    process_templates(conn, pool)
    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT template_id) FROM log_events")
        assert cur.fetchone()[0] == 1


def test_missing_drain_state_triggers_remine(conn, tmp_path):
    add_logs(conn, scenario_rows())
    process_templates(conn, MinerPool(str(tmp_path / "a")))
    fresh = MinerPool(str(tmp_path / "b"))  # simulates a lost state volume
    add_logs(conn, [(3, 40, "ERROR", "TypeError: 'NoneType' object is not subscriptable", 500, 30.0)])
    process_templates(conn, fresh)
    assert fresh.remined
    compute_features(conn, full=True)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM log_events WHERE template_id IS NULL")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM log_templates")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT errors FROM minute_features WHERE minute = %s", (BASE + timedelta(minutes=2),))
        assert cur.fetchone()[0] == 4
