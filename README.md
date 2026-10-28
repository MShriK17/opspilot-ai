# OpsPilot AI

An AI agent that investigates production incidents: it detects the problem, gathers evidence from logs, metrics and deploy history, consults runbooks, ranks likely root causes with citations, proposes a fix for **human approval**, and verifies whether the fix worked.

**Status: Week 3 of 10 - Detection and incidents.** A target app you can break on purpose, a collector, and a worker that turns logs into templates and per-minute features, detects anomalies, and opens incidents with a severity and a strict life cycle. Runbook RAG and the agent come next.

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

### Week 3 check: detection and incidents

```bash
python scripts/inject_failure.py start bad_deploy
# wait 20 seconds
python scripts/show_incidents.py              # an incident, with seconds between injection and detection
python scripts/show_incidents.py --id 1       # its signals and status history
python scripts/inject_failure.py reset        # the incident closes by itself about 2.5 minutes later
```

Detection times measured on a laptop with 5 simulated users: `bad_env_var` 5 s, `db_pool_exhausted` 5 s,
`bad_deploy` 8 s, `slow_dependency` 8 s, `memory_leak` 18 s. Severity rises as a failure develops
(for example SEV2 to SEV1), and each change is recorded.

**Warm-up:** error-rate and new-error detection work from the first request. Latency and memory detection
compare against the last ~30 minutes of history, so they start working after about 5 minutes of healthy traffic.

| Detector | Fires when (last 30 s vs. baseline median) | Severity |
|---|---|---|
| `error_rate` | 5xx rate above 5% and well above normal, at least 5 errors | 5% SEV3, 20% SEV2, 50% SEV1 |
| `latency` | p95 above 250 ms and 3x normal | SEV3, or SEV2 above 2 s |
| `memory_growth` | memory 40 MB above normal | SEV3, or SEV2 above 200 MB |
| `new_error_template` | an error type not seen in the baseline window, 3+ times | SEV3 |

Incident life cycle and rules: [docs/incident-state-machine.md](docs/incident-state-machine.md).

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
| `opspilot/detection/detectors.py` | The four detectors. Decision rules are pure functions, so they are unit tested without a database. Baselines use median and MAD, so a long-running failure cannot hide itself |
| `opspilot/incidents/state_machine.py` | Allowed status changes, enforced inside the database transaction, with an audit row for each |
| `opspilot/incidents/manager.py` | Opens an incident or attaches signals to the active one, raises severity, closes quiet incidents |
| `opspilot/worker/scheduler.py` | Every 10 seconds: template new logs, refresh features, run detectors, update incidents |

## Tests

```bash
make test        # 73 tests. Unit tests always run; integration tests need Postgres
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
- [x] Week 3: anomaly detection, incident manager, incident state machine
- [ ] Week 4: runbooks and RAG
- [ ] Weeks 5-10: agent, guardrails, approval and verification, evaluation, UI, deployment
