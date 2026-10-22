import os
import tempfile

# must be set before the app is imported
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"

import pytest
from fastapi.testclient import TestClient

from app.chaos import chaos
from app.config import settings
from app.main import app
from app.metrics import request_metrics

ADMIN = {"X-Admin-Token": "dev-token"}


@pytest.fixture()
def client():
    chaos.reset()
    request_metrics.reset()
    with TestClient(app) as c:
        yield c
    chaos.reset()
    settings.leak_limit_mb = 400
    settings.payment_timeout_s = 3.0
