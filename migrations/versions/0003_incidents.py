"""Week 3: incidents, detector signals, and an audit trail of status changes."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UP = """
CREATE TABLE IF NOT EXISTS incidents (
  id BIGSERIAL PRIMARY KEY,
  service_id INT NOT NULL REFERENCES services(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','investigating','awaiting_approval','remediating',
                      'verifying','resolved','escalated')),
  severity TEXT NOT NULL CHECK (severity IN ('SEV1','SEV2','SEV3','SEV4')),
  detector TEXT NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_signal_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  ground_truth_cause TEXT
);

-- The database itself guarantees at most one active incident per service,
-- so two workers can never open duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_incident
  ON incidents (service_id) WHERE status NOT IN ('resolved', 'escalated');
CREATE INDEX IF NOT EXISTS idx_incidents_detected ON incidents (detected_at DESC);

CREATE TABLE IF NOT EXISTS incident_signals (
  id BIGSERIAL PRIMARY KEY,
  incident_id BIGINT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  signal_key TEXT NOT NULL,
  detector TEXT NOT NULL,
  severity TEXT NOT NULL,
  score DOUBLE PRECISION,
  summary TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  template_id BIGINT REFERENCES log_templates(id),
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  hits INT NOT NULL DEFAULT 1,
  UNIQUE (incident_id, signal_key)
);

CREATE TABLE IF NOT EXISTS incident_events (
  id BIGSERIAL PRIMARY KEY,
  incident_id BIGINT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason TEXT,
  actor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incident_events ON incident_events (incident_id, ts);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UP)


def downgrade() -> None:
    b = op.get_bind()
    for t in ["incident_events", "incident_signals", "incidents"]:
        b.exec_driver_sql(f"DROP TABLE IF EXISTS {t} CASCADE")
