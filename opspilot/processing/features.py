"""Per-minute features built from logs: request count, error rate, latency, error templates.

These tables are what the Week 3 detector reads. Windows are recomputed from a couple of
minutes before the last computed minute, so a partly filled minute is corrected next cycle.
"""
FEATURES_SQL = """
WITH base AS (
  SELECT service_id,
         date_trunc('minute', ts) AS minute,
         ts, level, template_id,
         (attributes->>'status')::int AS status,
         (attributes->>'latency_ms')::float8 AS latency_ms,
         attributes->>'version' AS version
  FROM log_events
  WHERE ts >= %(start)s AND ts < %(end)s
),
agg AS (
  SELECT service_id, minute,
         count(*) FILTER (WHERE status IS NOT NULL) AS requests,
         count(*) FILTER (WHERE status >= 500) AS errors,
         avg(latency_ms) AS avg_latency_ms,
         percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
         count(DISTINCT template_id) FILTER (WHERE level IN ('ERROR', 'CRITICAL')) AS error_templates,
         (array_agg(version ORDER BY ts DESC) FILTER (WHERE version IS NOT NULL))[1] AS version
  FROM base GROUP BY service_id, minute
),
newt AS (
  SELECT service_id, date_trunc('minute', first_seen) AS minute, count(*) AS n
  FROM log_templates
  WHERE first_seen >= %(start)s AND first_seen < %(end)s
  GROUP BY service_id, date_trunc('minute', first_seen)
)
INSERT INTO minute_features
  (service_id, minute, requests, errors, error_rate, avg_latency_ms, p95_latency_ms,
   error_templates, new_templates, version)
SELECT a.service_id, a.minute, a.requests, a.errors,
       CASE WHEN a.requests > 0 THEN a.errors::float8 / a.requests ELSE 0 END,
       a.avg_latency_ms, a.p95_latency_ms, a.error_templates, COALESCE(n.n, 0), a.version
FROM agg a LEFT JOIN newt n ON n.service_id = a.service_id AND n.minute = a.minute
ON CONFLICT (service_id, minute) DO UPDATE SET
  requests = EXCLUDED.requests, errors = EXCLUDED.errors, error_rate = EXCLUDED.error_rate,
  avg_latency_ms = EXCLUDED.avg_latency_ms, p95_latency_ms = EXCLUDED.p95_latency_ms,
  error_templates = EXCLUDED.error_templates, new_templates = EXCLUDED.new_templates,
  version = EXCLUDED.version
"""

COUNTS_SQL = """
INSERT INTO template_minute_counts (service_id, minute, template_id, level, event_count)
SELECT service_id, date_trunc('minute', ts), template_id, level, count(*)
FROM log_events
WHERE ts >= %(start)s AND ts < %(end)s AND template_id IS NOT NULL
GROUP BY service_id, date_trunc('minute', ts), template_id, level
ON CONFLICT (service_id, minute, template_id, level) DO UPDATE SET event_count = EXCLUDED.event_count
"""


def compute_features(conn, full: bool = False) -> int:
    """Upsert minute_features and template_minute_counts. full=True rebuilds from the first log."""
    with conn.cursor() as cur:
        cur.execute("SELECT date_trunc('minute', min(ts)) FROM log_events")
        first_log = cur.fetchone()[0]
        if first_log is None:
            conn.commit()
            return 0
        start = first_log
        if not full:
            cur.execute("SELECT max(minute) - interval '2 minutes' FROM minute_features")
            last = cur.fetchone()[0]
            if last is not None:
                start = max(first_log, last)
        cur.execute("SELECT date_trunc('minute', now()) + interval '1 minute'")
        end = cur.fetchone()[0]
        params = {"start": start, "end": end}
        cur.execute(FEATURES_SQL, params)
        rows = cur.rowcount
        cur.execute(COUNTS_SQL, params)
    conn.commit()
    return rows
