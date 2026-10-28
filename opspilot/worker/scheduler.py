"""Worker loop: assign templates to new logs, then refresh per-minute features."""
import logging
import os
import time

import psycopg2

from opspilot.core.db import connect
from opspilot.detection.detectors import detect
from opspilot.incidents.manager import auto_resolve_quiet, handle_signals
from opspilot.processing.drain_parser import MinerPool, process_templates
from opspilot.processing.features import compute_features

INTERVAL_S = float(os.getenv("WORKER_INTERVAL_S", "10"))
STATE_DIR = os.getenv("DRAIN_STATE_DIR", "/state")
log = logging.getLogger("worker")


def detect_cycle(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM services")
        services = cur.fetchall()
    conn.commit()
    for service_id, name in services:
        signals = detect(conn, service_id)
        incident_id, created = handle_signals(conn, service_id, signals)
        if created:
            log.warning("INCIDENT %s opened for %s: %s", incident_id, name, "; ".join(s.summary for s in signals))
    for incident_id in auto_resolve_quiet(conn):
        log.info("incident %s resolved automatically (signals cleared)", incident_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pool = MinerPool(STATE_DIR)
    conn = connect()
    log.info("worker started (interval %.0fs, state %s)", INTERVAL_S, STATE_DIR)
    while True:
        try:
            mined = process_templates(conn, pool)
            rebuild = pool.remined
            pool.remined = False
            rows = compute_features(conn, full=rebuild)
            detect_cycle(conn)
            if mined or rebuild:
                log.info("templated %d new log lines, refreshed %d minute rows%s",
                         mined, rows, " (full rebuild)" if rebuild else "")
        except psycopg2.Error:
            log.exception("database error, reconnecting")
            try:
                conn.close()
            except psycopg2.Error:
                pass
            conn = connect()
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
