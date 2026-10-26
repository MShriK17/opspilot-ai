"""Assign every log line to a template using Drain3.

Why: thousands of lines such as 'QueuePool limit of size 2 ...' and '... size 3 ...' are
really one event type. Counting templates instead of raw lines is what lets the detector
spot a brand-new error and lets the agent see the top error types.
"""
import logging
import os

import psycopg2.extras
from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

log = logging.getLogger("opspilot.templates")

MASKS = [
    MaskingInstruction(r"\b[0-9a-f]{16}\b", "ID"),               # trace ids
    MaskingInstruction(r"\b\d+(\.\d+)?(ms|s)\b", "NUM"),         # durations such as 3.0s
    MaskingInstruction(r"\b\d+(\.\d+)?\b", "NUM"),               # plain numbers
]


def build_miner(state_path: str | None = None) -> TemplateMiner:
    config = TemplateMinerConfig()
    config.profiling_enabled = False
    config.mask_prefix, config.mask_suffix = "<", ">"
    config.masking_instructions = MASKS
    persistence = FilePersistence(state_path) if state_path else None
    return TemplateMiner(persistence, config)


class MinerPool:
    """One Drain3 miner per service, with its state saved to disk so cluster ids survive restarts."""

    def __init__(self, state_dir: str | None):
        self.state_dir = state_dir
        self._miners: dict[int, TemplateMiner] = {}
        self.remined = False  # set when a service had to be re-mined from scratch
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)

    def get(self, conn, service_id: int) -> TemplateMiner:
        if service_id not in self._miners:
            path = os.path.join(self.state_dir, f"drain_service_{service_id}.bin") if self.state_dir else None
            miner = build_miner(path)
            if len(miner.drain.clusters) == 0 and self._has_templates(conn, service_id):
                # Database has templates but the saved Drain state is gone: cluster ids would
                # no longer line up, so throw the old assignments away and mine again.
                log.warning("Drain state missing for service %s: re-mining from scratch", service_id)
                self._reset_service(conn, service_id)
                self.remined = True
            self._miners[service_id] = miner
        return self._miners[service_id]

    @staticmethod
    def _has_templates(conn, service_id: int) -> bool:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM log_templates WHERE service_id = %s LIMIT 1", (service_id,))
            return cur.fetchone() is not None

    @staticmethod
    def _reset_service(conn, service_id: int) -> None:
        with conn.cursor() as cur:
            cur.execute("UPDATE log_events SET template_id = NULL WHERE service_id = %s", (service_id,))
            cur.execute("DELETE FROM log_templates WHERE service_id = %s", (service_id,))  # cascades to counts
        conn.commit()


def process_templates(conn, pool: MinerPool, batch_size: int = 2000) -> int:
    """Mine templates for every log line that does not have one yet. Returns lines processed."""
    total = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, service_id, ts, message FROM log_events "
                "WHERE template_id IS NULL ORDER BY id LIMIT %s",
                (batch_size,),
            )
            rows = cur.fetchall()
        if not rows:
            return total

        latest: dict[tuple[int, int], list] = {}   # (service, cluster) -> [template text, first ts]
        assignments: list[tuple[int, tuple[int, int]]] = []
        touched = set()
        for log_id, service_id, ts, message in rows:
            miner = pool.get(conn, service_id)
            touched.add(service_id)
            result = miner.add_log_message(message)
            key = (service_id, result["cluster_id"])
            if key not in latest:
                latest[key] = [result["template_mined"], ts]
            else:
                latest[key][0] = result["template_mined"]
                latest[key][1] = min(latest[key][1], ts)
            assignments.append((log_id, key))

        template_ids: dict[tuple[int, int], int] = {}
        with conn.cursor() as cur:
            for (service_id, cluster_id), (template, first_ts) in latest.items():
                cur.execute(
                    """INSERT INTO log_templates (service_id, drain_cluster_id, template, first_seen)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (service_id, drain_cluster_id) DO UPDATE
                       SET template = EXCLUDED.template,
                           first_seen = LEAST(log_templates.first_seen, EXCLUDED.first_seen)
                       RETURNING id""",
                    (service_id, cluster_id, template, first_ts),
                )
                template_ids[(service_id, cluster_id)] = cur.fetchone()[0]
            psycopg2.extras.execute_values(
                cur,
                "UPDATE log_events e SET template_id = v.tid FROM (VALUES %s) AS v(id, tid) WHERE e.id = v.id",
                [(log_id, template_ids[key]) for log_id, key in assignments],
            )
        conn.commit()
        for service_id in touched:
            pool.get(conn, service_id).save_state("batch")
        total += len(rows)
