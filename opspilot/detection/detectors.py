"""Anomaly detectors.

Each detector compares the last 30 seconds with a robust baseline (median and MAD of the
previous ~30 minutes, ignoring the most recent 2 minutes). Median/MAD is used instead of
mean/std so that a failure that has lasted a while does not poison its own baseline.

The decision rules are pure functions (easy to unit test). `detect()` gathers the numbers
from Postgres and calls them.

Warm-up: error-rate detection works from the first request. Latency and memory detection
need about 5 minutes of healthy history, so they stay silent until the baseline exists.
"""
import statistics
from dataclasses import dataclass, field

SEVERITIES = ["SEV4", "SEV3", "SEV2", "SEV1"]  # lowest to highest

WINDOW_S = 30
BASELINE_MINUTES = 32
BASELINE_GAP_MINUTES = 2
MIN_BASELINE_ROWS = 3
MIN_WINDOW_REQUESTS = 20
MIN_ERRORS = 5
ERROR_RATE_FLOOR = 0.05
LATENCY_MIN_MS = 250
LATENCY_RATIO = 3.0
MEMORY_GROWTH_MB = 40
MEMORY_MIN_POINTS = 6
NEW_TEMPLATE_MIN_COUNT = 3


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


@dataclass
class Signal:
    detector: str              # error_rate | latency | memory_growth | new_error_template
    key: str                   # one signal row per (incident, key)
    severity: str
    score: float
    summary: str
    details: dict = field(default_factory=dict)
    template_id: int | None = None


def robust_baseline(values: list[float]) -> tuple[float, float] | None:
    """(median, sigma) where sigma = 1.4826 * MAD. None if there is too little history."""
    if len(values) < MIN_BASELINE_ROWS:
        return None
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return med, 1.4826 * mad


def error_rate_signal(requests: int, errors: int, baseline: tuple[float, float] | None) -> Signal | None:
    if requests < MIN_WINDOW_REQUESTS or errors < MIN_ERRORS:
        return None
    rate = errors / requests
    med, sigma = baseline or (0.0, 0.0)
    scale = max(sigma, 0.01)
    if rate < max(ERROR_RATE_FLOOR, med + 4 * scale):
        return None
    severity = "SEV1" if rate >= 0.5 else "SEV2" if rate >= 0.2 else "SEV3"
    return Signal(
        "error_rate", "error_rate", severity, round((rate - med) / scale, 1),
        f"HTTP 5xx error rate {rate:.0%} (normal {med:.1%})",
        {"window_requests": requests, "window_errors": errors, "error_rate": round(rate, 4),
         "baseline_median": round(med, 4)},
    )


def latency_signal(requests: int, p95_ms: float | None, baseline: tuple[float, float] | None) -> Signal | None:
    if baseline is None or p95_ms is None or requests < MIN_WINDOW_REQUESTS:
        return None
    med, sigma = baseline
    scale = max(sigma, 0.25 * med, 1.0)
    if p95_ms < max(LATENCY_MIN_MS, med * LATENCY_RATIO, med + 4 * scale):
        return None
    severity = "SEV2" if p95_ms >= 2000 else "SEV3"
    return Signal(
        "latency", "latency", severity, round((p95_ms - med) / scale, 1),
        f"p95 latency {p95_ms:.0f} ms (normal {med:.0f} ms)",
        {"window_requests": requests, "p95_ms": round(p95_ms, 1), "baseline_median_ms": round(med, 1)},
    )


def memory_signal(latest_mb: float | None, baseline_values: list[float]) -> Signal | None:
    if latest_mb is None or len(baseline_values) < MEMORY_MIN_POINTS:
        return None
    med = statistics.median(baseline_values)
    growth = latest_mb - med
    if growth < MEMORY_GROWTH_MB:
        return None
    return Signal(
        "memory_growth", "memory_growth", "SEV2" if growth >= 200 else "SEV3", round(growth, 1),
        f"Memory up {growth:.0f} MB to {latest_mb:.0f} MB (normal {med:.0f} MB)",
        {"memory_mb": round(latest_mb, 1), "baseline_median_mb": round(med, 1), "growth_mb": round(growth, 1)},
    )


def new_template_signal(template_id: int, template: str, count: int) -> Signal:
    return Signal(
        "new_error_template", f"new_error_template:{template_id}", "SEV3", float(count),
        f"New error type ({count} in {WINDOW_S}s): {template[:80]}",
        {"template": template, "count": count}, template_id=template_id,
    )


WINDOW_SQL = """
SELECT count(*) FILTER (WHERE status IS NOT NULL),
       count(*) FILTER (WHERE status >= 500),
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
FROM (SELECT (attributes->>'status')::int AS status, (attributes->>'latency_ms')::float8 AS latency_ms
      FROM log_events
      WHERE service_id = %(sid)s AND ts >= now() - make_interval(secs => %(win)s)) w
"""

BASELINE_SQL = """
SELECT error_rate, p95_latency_ms FROM minute_features
WHERE service_id = %(sid)s AND requests >= 30
  AND minute >= now() - make_interval(mins => %(span)s)
  AND minute < date_trunc('minute', now()) - make_interval(mins => %(gap)s)
"""

MEMORY_SQL = """
SELECT value, extract(epoch FROM now() - ts) AS age_s FROM metric_points
WHERE service_id = %(sid)s AND metric = 'memory_mb' AND ts >= now() - interval '32 minutes'
ORDER BY ts
"""

NEW_TEMPLATE_SQL = """
SELECT e.template_id, t.template, count(*) AS n
FROM log_events e JOIN log_templates t ON t.id = e.template_id
WHERE e.service_id = %(sid)s AND e.level IN ('ERROR', 'CRITICAL')
  AND e.ts >= now() - make_interval(secs => %(win)s)
  AND NOT EXISTS (
    SELECT 1 FROM template_minute_counts c
    WHERE c.service_id = e.service_id AND c.template_id = e.template_id
      AND c.level IN ('ERROR', 'CRITICAL')
      AND c.minute >= now() - make_interval(mins => %(span)s)
      AND c.minute < date_trunc('minute', now()) - make_interval(mins => %(gap)s))
GROUP BY e.template_id, t.template
HAVING count(*) >= %(minc)s
"""


def detect(conn, service_id: int) -> list[Signal]:
    """Run all detectors for one service against the database."""
    p = {"sid": service_id, "win": WINDOW_S, "span": BASELINE_MINUTES, "gap": BASELINE_GAP_MINUTES,
         "minc": NEW_TEMPLATE_MIN_COUNT}
    signals: list[Signal] = []
    with conn.cursor() as cur:
        cur.execute(WINDOW_SQL, p)
        requests, errors, p95 = cur.fetchone()
        cur.execute(BASELINE_SQL, p)
        rows = cur.fetchall()
        err_base = robust_baseline([r[0] for r in rows])
        lat_base = robust_baseline([r[1] for r in rows if r[1] is not None])
        cur.execute(MEMORY_SQL, p)
        mem = cur.fetchall()
        cur.execute(NEW_TEMPLATE_SQL, p)
        new_templates = cur.fetchall()
    conn.commit()  # end the read transaction so now() stays fresh next cycle

    latest = [v for v, age in mem if age <= 40]
    baseline_mem = [v for v, age in mem if age >= 90]
    for sig in (
        error_rate_signal(requests or 0, errors or 0, err_base),
        latency_signal(requests or 0, p95, lat_base),
        memory_signal(latest[-1] if latest else None, baseline_mem),
    ):
        if sig:
            signals.append(sig)
    signals.extend(new_template_signal(tid, tmpl, n) for tid, tmpl, n in new_templates)
    return signals
