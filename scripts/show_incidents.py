#!/usr/bin/env python3
"""List incidents, or show one in detail.

  python scripts/show_incidents.py            # recent incidents with time-to-detect
  python scripts/show_incidents.py --id 3     # signals and status history for one incident
"""
import argparse
import os

import psycopg2

URL = os.getenv("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")

LIST_SQL = """
SELECT i.id, to_char(i.detected_at AT TIME ZONE 'UTC', 'DD HH24:MI:SS') AS detected,
       i.severity, i.status,
       (SELECT j.scenario FROM injections j WHERE j.started_at <= i.detected_at
         ORDER BY j.started_at DESC LIMIT 1) AS scenario,
       (SELECT round(extract(epoch FROM i.detected_at - j.started_at)) FROM injections j
         WHERE j.started_at <= i.detected_at ORDER BY j.started_at DESC LIMIT 1) AS secs,
       (SELECT string_agg(DISTINCT s.detector, ',') FROM incident_signals s WHERE s.incident_id = i.id) AS detectors,
       i.title
FROM incidents i ORDER BY i.detected_at DESC LIMIT %s
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    with psycopg2.connect(URL) as conn, conn.cursor() as cur:
        if args.id:
            cur.execute("SELECT severity, status, title, detected_at FROM incidents WHERE id = %s", (args.id,))
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"incident {args.id} not found")
            print(f"Incident {args.id}  {row[0]}  {row[1]}\n{row[2]}\n\nSignals:")
            cur.execute("SELECT detector, severity, score, hits, summary FROM incident_signals "
                        "WHERE incident_id = %s ORDER BY first_seen", (args.id,))
            for det, sev, score, hits, summary in cur.fetchall():
                print(f"  [{sev}] {det:20} x{hits:<4} {summary}")
            print("\nHistory:")
            cur.execute("SELECT to_char(ts AT TIME ZONE 'UTC', 'HH24:MI:SS'), coalesce(from_status, '-'), to_status, actor, reason "
                        "FROM incident_events WHERE incident_id = %s ORDER BY id", (args.id,))
            for ts, a, b, actor, reason in cur.fetchall():
                print(f"  {ts}  {a} -> {b}  ({actor}) {reason}")
            return
        cur.execute(LIST_SQL, (args.limit,))
        print(f"{'ID':>3} {'DETECTED(UTC)':13} {'SEV':5} {'STATUS':12} {'INJECTED':18} {'SECS':>5}  DETECTORS / TITLE")
        for iid, det, sev, status, scenario, secs, detectors, title in cur.fetchall():
            secs_txt = "-" if secs is None else f"{int(secs)}"
            print(f"{iid:>3} {det:13} {sev:5} {status:12} {(scenario or '-'):18} {secs_txt:>5}  {detectors or '-'} | {title[:55]}")


if __name__ == "__main__":
    main()
