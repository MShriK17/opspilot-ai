# Changelog

## Week 3 - Detection and incidents
- Four detectors (error rate, latency, memory growth, new error type) using robust median/MAD baselines
- Incident manager: one active incident per service (enforced by a database index), signals attach instead of duplicating, severity only rises, quiet incidents close themselves
- Incident state machine with explicit paths for rejected approval, timeout, failed action and inconclusive verification; every change audited in `incident_events`
- Migration 0003, `scripts/show_incidents.py`, `docs/incident-state-machine.md`
- 49 new tests (73 total). All 5 scenarios detected in 5 to 18 seconds

## Week 2 - Templates and features
- Alembic migrations replace the Week 1 SQL script (0001 init, 0002 templates and features); a `migrate` service runs them before anything else starts
- Drain3 template mining per service, with saved state and automatic re-mining if the state is lost
- `minute_features` (requests, errors, error rate, latency, error templates, new templates, version) and `template_minute_counts`
- `worker` service refreshes both every 10 seconds
- `scripts/show_features.py` prints the per-minute view and top templates
- 9 new tests, including integration tests against real Postgres (run in CI)

## Week 1 - Foundation
- Target FastAPI app with structured JSON logging and rolling metrics
- Chaos switch with 5 failure scenarios and ground-truth file
- Locust load generator, Docker Compose stack (Postgres + pgvector, app, collector, load)
- Collector with transactional log offsets and metric polling
- `inject_failure.py` records deploy/config events and injection windows
- Tests for every scenario, the connection gate, and the log parser
