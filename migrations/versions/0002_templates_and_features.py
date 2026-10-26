"""Week 2: Drain3 cluster ids on templates, per-minute features, per-minute template counts."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UP = """
-- Drain3 can rewrite a template as it generalises, so templates are keyed by cluster id,
-- not by text.
ALTER TABLE log_templates ADD COLUMN IF NOT EXISTS drain_cluster_id INT;
ALTER TABLE log_templates DROP CONSTRAINT IF EXISTS log_templates_service_id_template_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_cluster ON log_templates (service_id, drain_cluster_id);

-- Fast lookup of logs still waiting for a template
CREATE INDEX IF NOT EXISTS idx_log_unmined ON log_events (id) WHERE template_id IS NULL;

CREATE TABLE IF NOT EXISTS minute_features (
  service_id INT NOT NULL REFERENCES services(id),
  minute TIMESTAMPTZ NOT NULL,
  requests INT NOT NULL DEFAULT 0,
  errors INT NOT NULL DEFAULT 0,
  error_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
  avg_latency_ms DOUBLE PRECISION,
  p95_latency_ms DOUBLE PRECISION,
  error_templates INT NOT NULL DEFAULT 0,
  new_templates INT NOT NULL DEFAULT 0,
  version TEXT,
  PRIMARY KEY (service_id, minute)
);

CREATE TABLE IF NOT EXISTS template_minute_counts (
  service_id INT NOT NULL REFERENCES services(id),
  minute TIMESTAMPTZ NOT NULL,
  template_id BIGINT NOT NULL REFERENCES log_templates(id) ON DELETE CASCADE,
  level TEXT NOT NULL,
  event_count INT NOT NULL,
  PRIMARY KEY (service_id, minute, template_id, level)
);
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UP)


def downgrade() -> None:
    b = op.get_bind()
    b.exec_driver_sql("DROP TABLE IF EXISTS template_minute_counts")
    b.exec_driver_sql("DROP TABLE IF EXISTS minute_features")
    b.exec_driver_sql("DROP INDEX IF EXISTS idx_log_unmined")
    b.exec_driver_sql("DROP INDEX IF EXISTS uq_template_cluster")
    b.exec_driver_sql("ALTER TABLE log_templates DROP COLUMN IF EXISTS drain_cluster_id")
