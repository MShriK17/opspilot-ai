# Changelog

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
