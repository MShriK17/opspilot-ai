#!/usr/bin/env python3
"""Show what Week 2 produces.

  python scripts/show_features.py                 # last 10 minutes: traffic, errors, top error template
  python scripts/show_features.py --minutes 30
  python scripts/show_features.py --templates     # top templates in the window
"""
import argparse
import os

import psycopg2

URL = os.getenv("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")

MINUTES_SQL = """
SELECT to_char(f.minute AT TIME ZONE 'UTC', 'DD HH24:MI') AS minute, f.requests, f.errors,
       round((f.error_rate * 100)::numeric, 1) AS err_pct,
       round(coalesce(f.p95_latency_ms, 0)::numeric, 0) AS p95_ms,
       coalesce(f.version, '-') AS version, f.new_templates,
       coalesce((SELECT t.template FROM template_minute_counts c
                 JOIN log_templates t ON t.id = c.template_id
                 WHERE c.service_id = f.service_id AND c.minute = f.minute
                   AND c.level IN ('ERROR', 'CRITICAL')
                 ORDER BY c.event_count DESC LIMIT 1), '') AS top_error_template
FROM minute_features f
ORDER BY f.minute DESC LIMIT %s
"""

TEMPLATES_SQL = """
SELECT c.level, sum(c.event_count) AS n, t.template
FROM template_minute_counts c JOIN log_templates t ON t.id = c.template_id
WHERE c.minute >= (SELECT max(minute) FROM minute_features) - make_interval(mins => %s)
GROUP BY c.level, t.template ORDER BY n DESC LIMIT 15
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--templates", action="store_true")
    args = ap.parse_args()
    with psycopg2.connect(URL) as conn, conn.cursor() as cur:
        if args.templates:
            cur.execute(TEMPLATES_SQL, (args.minutes,))
            print(f"{'LEVEL':8} {'COUNT':>7}  TEMPLATE")
            for level, n, template in cur.fetchall():
                print(f"{level:8} {n:>7}  {template[:90]}")
            return
        cur.execute(MINUTES_SQL, (args.minutes,))
        rows = cur.fetchall()[::-1]
        print(f"{'DD HH:MM UTC':12} {'REQ':>5} {'ERR':>5} {'ERR%':>6} {'P95ms':>6} {'VER':8} {'NEW':>3}  TOP ERROR TEMPLATE")
        for minute, req, err, pct, p95, ver, new, top in rows:
            print(f"{minute:12} {req:>5} {err:>5} {pct:>6} {int(p95):>6} {ver:8} {new:>3}  {top[:60]}")


if __name__ == "__main__":
    main()
