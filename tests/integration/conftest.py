"""Integration tests need a real Postgres. Set TEST_DATABASE_URL to a database whose name
contains 'test' - it is wiped on every run. Without it these tests are skipped."""
import os
from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture()
def conn(monkeypatch):
    if not URL:
        pytest.skip("TEST_DATABASE_URL not set")
    assert "test" in URL.rsplit("/", 1)[-1], "refusing to wipe a database whose name does not contain 'test'"
    c = psycopg2.connect(URL)
    with c.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    c.commit()
    monkeypatch.setenv("OPSPILOT_DATABASE_URL", URL)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    yield c
    c.close()
