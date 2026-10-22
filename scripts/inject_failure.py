#!/usr/bin/env python3
"""Break and heal the target app.

  python scripts/inject_failure.py list
  python scripts/inject_failure.py start bad_deploy
  python scripts/inject_failure.py status
  python scripts/inject_failure.py reset
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import requests

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-token")
DATABASE_URL = os.getenv("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")
SERVICE = os.getenv("SERVICE_NAME", "target-app")
SCENARIOS = json.loads(
    (Path(__file__).resolve().parent.parent / "evaluation/scenarios/scenarios.json").read_text()
)
HEADERS = {"X-Admin-Token": ADMIN_TOKEN}


def admin(method: str, path: str) -> dict:
    r = requests.request(method, f"{TARGET_URL}{path}", headers=HEADERS, timeout=5)
    r.raise_for_status()
    return r.json()


def service_id(cur) -> int:
    cur.execute("INSERT INTO services (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (SERVICE,))
    cur.execute("SELECT id FROM services WHERE name = %s", (SERVICE,))
    return cur.fetchone()[0]


def record_deploy(cur, sid: int, event: dict) -> None:
    cur.execute(
        """INSERT INTO deployments (service_id, version, git_sha, change_summary, config_diff, deployed_at)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            sid,
            event["version"],
            event.get("git_sha"),
            event["change_summary"],
            json.dumps(event["config_diff"]) if event.get("config_diff") else None,
            datetime.now(timezone.utc),
        ),
    )


def start(name: str) -> None:
    if name not in SCENARIOS:
        sys.exit(f"unknown scenario '{name}'. choose from: {', '.join(SCENARIOS)}")
    current = admin("GET", "/admin/chaos")["scenario"]
    if current:
        sys.exit(f"scenario '{current}' is already active. run: reset")
    sc = SCENARIOS[name]
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        sid = service_id(cur)
        if sc["deploy_event"]:
            record_deploy(cur, sid, sc["deploy_event"])
        cur.execute(
            "INSERT INTO injections (scenario, ground_truth_cause, correct_playbook, started_at) VALUES (%s, %s, %s, %s)",
            (name, sc["ground_truth_cause"], sc["correct_playbook"], datetime.now(timezone.utc)),
        )
    admin("POST", f"/admin/chaos/{name}")
    print(f"BROKEN: {name} - {sc['description']}")


def reset() -> None:
    current = admin("GET", "/admin/chaos")["scenario"]
    if not current:
        print("nothing to heal: app is healthy")
        return
    sc = SCENARIOS[current]
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        sid = service_id(cur)
        if sc["deploy_event"]:
            record_deploy(
                cur,
                sid,
                {"version": "v1.0.0", "git_sha": None, "change_summary": "Rollback to v1.0.0", "config_diff": None},
            )
        cur.execute(
            "UPDATE injections SET ended_at = %s WHERE scenario = %s AND ended_at IS NULL",
            (datetime.now(timezone.utc), current),
        )
    admin("POST", "/admin/chaos/reset")
    print(f"HEALED: {current}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        for name, sc in SCENARIOS.items():
            print(f"{name:20s} {sc['description']}")
    elif cmd == "start" and len(sys.argv) == 3:
        start(sys.argv[2])
    elif cmd == "reset":
        reset()
    elif cmd == "status":
        print(json.dumps(admin("GET", "/admin/chaos"), indent=2))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
