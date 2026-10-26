# OpsPilot AI

An AI agent that investigates production incidents: it detects the problem, gathers evidence from logs, metrics and deploy history, consults runbooks, ranks likely root causes with citations, proposes a fix for **human approval**, and verifies whether the fix worked.

**Status: Week 2 of 10 - Templates and features.** A target app you can break on purpose, a collector that stores logs and metrics, and a worker that turns raw logs into log templates and per-minute features. Detection, RAG and the agent come in later weeks.

## Quick start

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
make up                                                  # builds and starts everything
```

Services: `postgres` (5432), `migrate` (runs once, then exits - this is normal), `target-app` (8000), `collector`, `worker`, `load-generator` (5 simulated users).

### Check that it works (this is the Week 1 "done" test)

```bash
make counts          # log rows by level + metric rows are growing
make break SCENARIO=bad_deploy
sleep 30
make recent-errors   # TypeError lines from /checkout
curl localhost:8000/metrics
make heal
```

### Week 2 check: see templates and per-minute features

```bash
python scripts/inject_failure.py start bad_deploy
# wait 60 seconds
python scripts/show_features.py                 # per-minute requests, error %, p95, top error template
python scripts/show_features.py --templates     # most frequent log templates
python scripts/inject_failure.py reset
```

You should see one minute row where `ERR%` jumps, the version changes to `v2.0.0`, and the top error template is `TypeError: 'NoneType' object is not subscriptable`.

## Failure scenarios

| Scenario | What you will see | Root cause (ground truth) | Correct fix |
|---|---|---|---|
| `bad_deploy` | `TypeError: 'NoneType' object is not subscriptable` on checkout, version `v2.0.0` | Code bug in new version | rollback_deployment |
| `db_pool_exhausted` | `PoolTimeout: QueuePool limit of size 2...`, p95 latency in seconds | DB connection pool exhaustion | revert_config |
| `slow_dependency` | `DependencyTimeout: payment-gateway timed out`, high latency | Slow payment gateway | toggle_feature_flag |
| `memory_leak` | `memory_mb` climbs about 3 MB/s, then `MemoryError` after about 2 minutes, version `v1.1.0` | Leak in new cache | rollback_deployment |
| `bad_env_var` | `DatabaseUnavailable: could not translate host name 'db-prod-typo'` on every DB endpoint, `/health` still OK | Wrong DATABASE_HOST | revert_config |

Ground truth, deploy events and correct playbooks live in `evaluation/scenarios/scenarios.json`. The Week 8 evaluation harness reads the same file.

Commands: `make scenarios` (list), `make break SCENARIO=<name>`, `make status`, `make heal`.

## What each piece does

| Path | Role |
|---|---|
| `target_app/` | FastAPI shop (`/products`, `/checkout`, `/orders/{id}`, `/metrics`, `/health`) with JSON logs and a chaos switch (`/admin/chaos/...`, token header) |
| `load_generator/` | Locust traffic: browse, checkout (30% with coupon), order lookup |
| `opspilot/ingestion/collector.py` | Tails the JSON log file and polls `/metrics` every 10 s into Postgres. Log offsets are saved in the same transaction as the rows, so restarts never duplicate lines |
| `scripts/inject_failure.py` | Starts and heals a scenario, records the deploy or config event and the injection window in Postgres |
| `migrations/` | Alembic migrations (plain SQL). `0001` Week 1 tables, `0002` templates and features. Run by the `migrate` service on every `docker compose up` |
| `opspilot/processing/drain_parser.py` | Drain3 log template mining. Templates are keyed by Drain cluster id, so a template can generalise without splitting its history. If the saved Drain state is lost, the service is re-mined from scratch |
| `opspilot/processing/features.py` | Builds `minute_features` and `template_minute_counts` from logs. Recomputes the last few minutes each cycle so partly filled minutes self-correct |
| `opspilot/worker/scheduler.py` | Every 10 seconds: template new logs, refresh features |

## Tests

```bash
make test        # 24 tests. Unit tests always run; integration tests need Postgres
# integration tests wipe the database they run against, so its name must contain 'test':
#   TEST_DATABASE_URL=postgresql://opspilot:opspilot@localhost:5432/opspilot_test pytest
```

## Honest notes

- The admin endpoints and `dev-token` are for local use only. Never expose them publicly.
- `db_pool_exhausted` simulates a pool with a counting gate in front of Postgres, and mimics SQLAlchemy's error text. It is a model of the failure, not a real pool.
- Logs are data, not instructions. Later weeks add a test that a log line saying "ignore previous instructions" does not steer the agent.

## Roadmap

- [x] Week 1: target app, chaos, load, collector, schema
- [x] Week 2: Drain3 log templates, per-minute features, Alembic migrations
- [ ] Week 3: anomaly detection and incident manager (with the incident state machine)
- [ ] Week 4: runbooks and RAG
- [ ] Weeks 5-10: agent, guardrails, approval and verification, evaluation, UI, deployment
