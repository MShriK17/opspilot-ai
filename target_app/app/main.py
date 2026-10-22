"""Target application: a small shop API that OpsPilot AI will investigate."""
import time
import traceback
import uuid
from contextlib import asynccontextmanager

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import payment, pricing
from .chaos import SCENARIO_VERSIONS, chaos
from .config import settings
from .db import Order, Product, db_session, gate, init_db
from .logging_config import setup_logging
from .metrics import request_metrics

log = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("application started", extra={"ctx": {"trace_id": None}})
    yield


app = FastAPI(title="target-app", lifespan=lifespan)


class Coupon(BaseModel):
    code: str
    percent: float = Field(ge=0, le=90)


class CheckoutRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=20)
    coupon: Coupon | None = None


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


@app.middleware("http")
async def observe(request: Request, call_next):
    trace_id = uuid.uuid4().hex[:16]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # unhandled error inside an endpoint
        latency_ms = (time.perf_counter() - start) * 1000
        request_metrics.record(500, latency_ms)
        log.error(
            f"{type(exc).__name__}: {exc}",
            extra={
                "ctx": {
                    "trace_id": trace_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status": 500,
                    "latency_ms": round(latency_ms, 1),
                    "exception": type(exc).__name__,
                    "traceback": traceback.format_exc()[-1200:],
                }
            },
        )
        return JSONResponse({"detail": "internal error", "trace_id": trace_id}, status_code=500)
    latency_ms = (time.perf_counter() - start) * 1000
    request_metrics.record(response.status_code, latency_ms)
    if not request.url.path.startswith("/admin"):
        log.info(
            "request completed",
            extra={
                "ctx": {
                    "trace_id": trace_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status": response.status_code,
                    "latency_ms": round(latency_ms, 1),
                }
            },
        )
    return response


@app.get("/health")
def health():
    return {"status": "ok", "version": chaos.version}


@app.get("/products")
def list_products():
    with db_session() as s:
        return [{"id": p.id, "name": p.name, "price": p.price} for p in s.query(Product).all()]


@app.post("/checkout")
def checkout(req: CheckoutRequest):
    chaos.maybe_leak()
    with db_session() as s:
        product = s.get(Product, req.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    coupon = req.coupon.model_dump() if req.coupon else None
    total = pricing.calculate_total(product.price, req.quantity, coupon)
    payment.charge(total)  # outside the DB session on purpose
    with db_session() as s:
        order = Order(product_id=product.id, quantity=req.quantity, total=total, status="paid")
        s.add(order)
        s.commit()
        return {"order_id": order.id, "total": total}


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    with db_session() as s:
        order = s.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        return {"id": order.id, "total": order.total, "status": order.status}


@app.get("/metrics")
def metrics():
    snap = request_metrics.snapshot()
    snap["memory_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    snap["db_pool_in_use"] = gate.in_use
    snap["version"] = chaos.version
    return snap


@app.get("/admin/chaos", dependencies=[Depends(require_admin)])
def chaos_status():
    return {"scenario": chaos.scenario, "version": chaos.version, "started_at": chaos.started_at}


@app.post("/admin/chaos/reset", dependencies=[Depends(require_admin)])
def chaos_reset():
    previous = chaos.scenario
    chaos.reset()
    request_metrics.reset()
    log.info("service restarted", extra={"ctx": {"trace_id": None}})
    return {"scenario": None, "previous": previous, "version": chaos.version}


@app.post("/admin/chaos/{scenario}", dependencies=[Depends(require_admin)])
def chaos_start(scenario: str):
    if scenario not in SCENARIO_VERSIONS:
        raise HTTPException(status_code=404, detail=f"unknown scenario, choose from {sorted(SCENARIO_VERSIONS)}")
    chaos.activate(scenario)
    log.info("service restarted", extra={"ctx": {"trace_id": None}})
    return {"scenario": scenario, "version": chaos.version}
