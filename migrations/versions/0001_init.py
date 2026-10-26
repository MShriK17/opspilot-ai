"""Week 1 schema: services, deployments, logs, metrics, injections, ingest offsets.

Written with IF NOT EXISTS so it is safe on databases created by the Week 1 SQL script.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UP = """
CREATE TABLE IF NOT EXISTS services (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  owner_team TEXT,
  runbook_path TEXT
);

CREATE TABLE IF NOT EXISTS deployments (
  id BIGSERIAL PRIMARY KEY,
  service_id INT REFERENCES services(id),
  version TEXT NOT NULL,
  git_sha TEXT,
  change_summary TEXT,
  config_diff JSONB,
  deployed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS log_templates (
  id BIGSERIAL PRIMARY KEY,
  service_id INT REFERENCES services(id),
  template TEXT NOT NULL,
  first_seen TIMESTAMPTZ,
  UNIQUE (service_id, template)
);

CREATE TABLE IF NOT EXISTS log_events (
  id BIGSERIAL PRIMARY KEY,
  service_id INT REFERENCES services(id),
  ts TIMESTAMPTZ NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  template_id BIGINT REFERENCES log_templates(id),
  trace_id TEXT,
  attributes JSONB
);
CREATE INDEX IF NOT EXISTS idx_log_service_ts ON log_events (service_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_log_template_ts ON log_events (template_id, ts);

CREATE TABLE IF NOT EXISTS metric_points (
  service_id INT REFERENCES services(id),
  metric TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (service_id, metric, ts)
);

CREATE TABLE IF NOT EXISTS injections (
  id BIGSERIAL PRIMARY KEY,
  scenario TEXT NOT NULL,
  ground_truth_cause TEXT,
  correct_playbook TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ingest_offsets (
  source TEXT PRIMARY KEY,
  byte_offset BIGINT NOT NULL
);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UP)


def downgrade() -> None:
    for t in ["ingest_offsets", "injections", "metric_points", "log_events",
              "log_templates", "deployments", "services"]:
        op.get_bind().exec_driver_sql(f"DROP TABLE IF EXISTS {t} CASCADE")
