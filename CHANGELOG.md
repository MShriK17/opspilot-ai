# Changelog

## Week 1 - Foundation
- Target FastAPI app with structured JSON logging and rolling metrics
- Chaos switch with 5 failure scenarios and ground-truth file
- Locust load generator, Docker Compose stack (Postgres + pgvector, app, collector, load)
- Collector with transactional log offsets and metric polling
- `inject_failure.py` records deploy/config events and injection windows
- Tests for every scenario, the connection gate, and the log parser
