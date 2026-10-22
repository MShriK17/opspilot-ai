"""Chaos switch: one global scenario that changes how the app misbehaves.

Scenarios (ground truth lives in evaluation/scenarios/scenarios.json):
  bad_deploy         v2.0.0 pricing code crashes when no coupon is sent
  db_pool_exhausted  pool shrinks to 2 connections and queries get slow
  slow_dependency    payment gateway becomes slow and times out
  memory_leak        v1.1.0 cache never frees memory
  bad_env_var        database host is misconfigured
"""
import gc
import threading
import time

from .config import settings

BASE_VERSION = "v1.0.0"
SCENARIO_VERSIONS = {
    "bad_deploy": "v2.0.0",
    "memory_leak": "v1.1.0",
    "db_pool_exhausted": BASE_VERSION,
    "slow_dependency": BASE_VERSION,
    "bad_env_var": BASE_VERSION,
}
NORMAL_POOL_SIZE = 10
CHAOS_POOL_SIZE = 2
MB = 1024 * 1024


class ChaosState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.scenario: str | None = None
        self.started_at: float | None = None
        self._leak: list[bytearray] = []

    @property
    def version(self) -> str:
        return SCENARIO_VERSIONS.get(self.scenario, BASE_VERSION)

    def is_active(self, name: str) -> bool:
        return self.scenario == name

    def pool_size(self) -> int:
        return CHAOS_POOL_SIZE if self.is_active("db_pool_exhausted") else NORMAL_POOL_SIZE

    def activate(self, name: str) -> None:
        if name not in SCENARIO_VERSIONS:
            raise ValueError(f"unknown scenario: {name}")
        with self._lock:
            self._free_leak()
            self.scenario = name
            self.started_at = time.time()

    def reset(self) -> None:
        with self._lock:
            self._free_leak()
            self.scenario = None
            self.started_at = None

    def leaked_mb(self) -> int:
        return len(self._leak)

    def maybe_leak(self) -> None:
        """Called on every checkout. Leaks 1 MB per call while memory_leak is active."""
        if not self.is_active("memory_leak"):
            return
        with self._lock:
            if len(self._leak) >= settings.leak_limit_mb:
                raise MemoryError("Cannot allocate memory: worker heap exhausted")
            self._leak.append(bytearray(b"\x01") * MB)  # touch pages so RSS really grows

    def _free_leak(self) -> None:
        self._leak.clear()
        gc.collect()


chaos = ChaosState()
