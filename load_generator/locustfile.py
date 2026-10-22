import random

from locust import HttpUser, between, task


class Shopper(HttpUser):
    wait_time = between(0.2, 0.8)

    @task(5)
    def browse(self):
        self.client.get("/products")

    @task(3)
    def checkout(self):
        body = {"product_id": random.randint(1, 5), "quantity": random.randint(1, 3)}
        if random.random() < 0.3:
            body["coupon"] = {"code": "SAVE10", "percent": 10}
        self.client.post("/checkout", json=body)

    @task(1)
    def lookup_order(self):
        with self.client.get(
            f"/orders/{random.randint(1, 50)}", name="/orders/[id]", catch_response=True
        ) as r:
            if r.status_code == 404:
                r.success()

    @task(1)
    def health(self):
        self.client.get("/health")
