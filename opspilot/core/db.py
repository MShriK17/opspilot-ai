import logging
import os
import time

import psycopg2

log = logging.getLogger("opspilot.db")
DATABASE_URL = os.getenv("OPSPILOT_DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5432/opspilot")


def connect(url: str | None = None, retries: int = 30):
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(url or DATABASE_URL)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as exc:
            log.warning("database not ready (%s), retry %d/%d", exc, attempt + 1, retries)
            time.sleep(2)
    raise RuntimeError("could not connect to database")
