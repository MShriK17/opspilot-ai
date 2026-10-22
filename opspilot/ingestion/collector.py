"""Collector: tails the target app's JSON log file and polls its /metrics endpoint,
writing both into Postgres. Log offsets are stored in the same transaction as the
rows, so restarts never duplicate or lose lines."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests

DATABASE_URL = os.getenv("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")
LOG_FILE = os.getenv("LOG_FILE", "/var/log/target/app.log")
METRICS_URL = os.getenv("TARGET_METRICS_URL", "http://localhost:8000/metrics")
METRIC_INTERVAL_S = float(os.getenv("METRIC_INTERVAL_S", "10"))
FLUSH_INTERVAL_S = 1.0
BATCH_SIZE = 200
METRIC_KEYS = ("rps", "error_rate", "p95_latency_ms", "memory_mb", "db_pool_in_use")

log = logging.getLogger("collector")


def parse_log_line(line: str) -> dict | None:
    """Parse one JSON log line into a row dict. Returns None for bad lines."""
    try:
        raw = json.loads(line)
        return {
            "service": raw["service"],
            "ts": datetime.fromisoformat(raw["ts"]),
            "level": raw["level"],
            "message": raw["message"],
            "trace_id": raw.get("trace_id"),
            "attributes": {**raw.get("attributes", {}), "version": raw.get("version")},
        }
    except (ValueError, KeyError, TypeError):
        return None


def connect(retries: int = 30):
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as exc:
            log.warning("database not ready (%s), retry %d/%d", exc, attempt + 1, retries)
            time.sleep(2)
    raise RuntimeError("could not connect to database")


def get_service_id(conn, name: str, cache: dict) -> int:
    if name not in cache:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO services (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
            cur.execute("SELECT id FROM services WHERE name = %s", (name,))
            cache[name] = cur.fetchone()[0]
        conn.commit()
    return cache[name]


def flush_logs(conn, rows: list[dict], offset: int, cache: dict) -> None:
    values = [
        (
            get_service_id(conn, r["service"], cache),
            r["ts"],
            r["level"],
            r["message"],
            r["trace_id"],
            psycopg2.extras.Json(r["attributes"]),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        if values:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO log_events (service_id, ts, level, message, trace_id, attributes) VALUES %s",
                values,
            )
        cur.execute(
            """INSERT INTO ingest_offsets (source, byte_offset) VALUES (%s, %s)
               ON CONFLICT (source) DO UPDATE SET byte_offset = EXCLUDED.byte_offset""",
            (LOG_FILE, offset),
        )
    conn.commit()


def tail_logs(stop: threading.Event) -> None:
    conn = connect()
    cache: dict = {}
    with conn.cursor() as cur:
        cur.execute("SELECT byte_offset FROM ingest_offsets WHERE source = %s", (LOG_FILE,))
        row = cur.fetchone()
    offset = row[0] if row else 0
    conn.commit()

    while not stop.is_set():
        if not os.path.exists(LOG_FILE):
            time.sleep(1)
            continue
        if os.path.getsize(LOG_FILE) < offset:  # file was recreated
            offset = 0
        batch: list[dict] = []
        last_flush = time.monotonic()
        with open(LOG_FILE, "rb") as f:
            f.seek(offset)
            while not stop.is_set():
                pos = f.tell()
                line = f.readline()
                if line and line.endswith(b"\n"):
                    parsed = parse_log_line(line.decode("utf-8", errors="replace"))
                    if parsed:
                        batch.append(parsed)
                    offset = f.tell()
                else:
                    f.seek(pos)  # partial line: wait for the rest
                    time.sleep(0.2)
                    if os.path.getsize(LOG_FILE) < offset:
                        break  # truncated, reopen
                due = time.monotonic() - last_flush >= FLUSH_INTERVAL_S
                if batch and (len(batch) >= BATCH_SIZE or due):
                    flush_logs(conn, batch, offset, cache)
                    batch, last_flush = [], time.monotonic()
                elif not batch and due:
                    last_flush = time.monotonic()


def poll_metrics(stop: threading.Event) -> None:
    conn = connect()
    cache: dict = {}
    while not stop.is_set():
        try:
            data = requests.get(METRICS_URL, timeout=3).json()
            service_id = get_service_id(conn, os.getenv("SERVICE_NAME", "target-app"), cache)
            now = datetime.now(timezone.utc)
            rows = [(service_id, k, now, float(data[k])) for k in METRIC_KEYS if k in data]
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO metric_points (service_id, metric, ts, value) VALUES %s ON CONFLICT DO NOTHING",
                    rows,
                )
            conn.commit()
        except (requests.RequestException, ValueError) as exc:
            log.warning("metrics poll failed: %s", exc)
        except psycopg2.Error:
            conn.rollback()
            log.exception("metrics insert failed")
        stop.wait(METRIC_INTERVAL_S)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = threading.Event()
    threads = [
        threading.Thread(target=tail_logs, args=(stop,), name="logs", daemon=True),
        threading.Thread(target=poll_metrics, args=(stop,), name="metrics", daemon=True),
    ]
    for t in threads:
        t.start()
    log.info("collector started: logs=%s metrics=%s", LOG_FILE, METRICS_URL)
    try:
        while True:
            time.sleep(1)
            if not all(t.is_alive() for t in threads):
                raise RuntimeError("a collector thread died")
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
