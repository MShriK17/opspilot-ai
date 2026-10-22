import pytest

from app.config import settings
from app.db import ConnectionGate, PoolTimeout

ADMIN = {"X-Admin-Token": "dev-token"}

NO_COUPON = {"product_id": 1, "quantity": 2}
WITH_COUPON = {"product_id": 1, "quantity": 2, "coupon": {"code": "SAVE10", "percent": 10}}


def start(client, name):
    return client.post(f"/admin/chaos/{name}", headers=ADMIN)


def test_health_and_products(client):
    assert client.get("/health").json() == {"status": "ok", "version": "v1.0.0"}
    assert len(client.get("/products").json()) == 5


def test_checkout_works_normally(client):
    r = client.post("/checkout", json=WITH_COUPON)
    assert r.status_code == 200
    assert r.json()["total"] == 216.0  # 120 * 2 * 0.9
    assert client.post("/checkout", json=NO_COUPON).status_code == 200


def test_unknown_product_is_404_not_500(client):
    assert client.post("/checkout", json={"product_id": 999}).status_code == 404


def test_admin_requires_token(client):
    assert client.post("/admin/chaos/bad_deploy").status_code == 401
    assert client.get("/admin/chaos", headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_unknown_scenario_rejected(client):
    assert start(client, "nope").status_code == 404


def test_bad_deploy_breaks_checkout_without_coupon(client):
    assert start(client, "bad_deploy").json()["version"] == "v2.0.0"
    assert client.post("/checkout", json=NO_COUPON).status_code == 500
    assert client.post("/checkout", json=WITH_COUPON).status_code == 200
    assert client.get("/health").json()["version"] == "v2.0.0"


def test_reset_restores_health(client):
    start(client, "bad_deploy")
    assert client.post("/checkout", json=NO_COUPON).status_code == 500
    client.post("/admin/chaos/reset", headers=ADMIN)
    assert client.post("/checkout", json=NO_COUPON).status_code == 200
    assert client.get("/health").json()["version"] == "v1.0.0"


def test_bad_env_var_breaks_db_endpoints_but_not_health(client):
    start(client, "bad_env_var")
    assert client.get("/products").status_code == 500
    assert client.get("/health").status_code == 200


def test_slow_dependency_times_out(client):
    settings.payment_timeout_s = 0.05  # keep the test fast
    start(client, "slow_dependency")
    assert client.post("/checkout", json=WITH_COUPON).status_code == 500


def test_memory_leak_grows_then_fails(client):
    settings.leak_limit_mb = 2
    start(client, "memory_leak")
    assert client.post("/checkout", json=WITH_COUPON).status_code == 200
    assert client.post("/checkout", json=WITH_COUPON).status_code == 200
    assert client.post("/checkout", json=WITH_COUPON).status_code == 500
    client.post("/admin/chaos/reset", headers=ADMIN)
    assert client.post("/checkout", json=WITH_COUPON).status_code == 200


def test_connection_gate_times_out_when_full():
    gate = ConnectionGate(lambda: 1)
    gate.acquire(0.05)
    with pytest.raises(PoolTimeout):
        gate.acquire(0.05)
    gate.release()
    gate.acquire(0.05)


def test_metrics_report_error_rate(client):
    start(client, "bad_deploy")
    for _ in range(4):
        client.post("/checkout", json=NO_COUPON)
    m = client.get("/metrics").json()
    assert m["error_rate"] > 0.5
    assert {"rps", "p95_latency_ms", "memory_mb", "db_pool_in_use", "version"} <= m.keys()
