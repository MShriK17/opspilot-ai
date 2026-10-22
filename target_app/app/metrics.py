"""Rolling 30-second request metrics."""
import threading
import time
from collections import deque

WINDOW_S = 30


class RollingMetrics:
    def __init__(self) -> None:
        self._events: deque[tuple[float, int, float]] = deque()
        self._lock = threading.Lock()

    def record(self, status: int, latency_ms: float) -> None:
        now = time.time()
        with self._lock:
            self._events.append((now, status, latency_ms))
            self._trim(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _trim(self, now: float) -> None:
        while self._events and self._events[0][0] < now - WINDOW_S:
            self._events.popleft()

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            self._trim(now)
            events = list(self._events)
        if not events:
            return {"rps": 0.0, "error_rate": 0.0, "p95_latency_ms": 0.0}
        latencies = sorted(e[2] for e in events)
        errors = sum(1 for e in events if e[1] >= 500)
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        return {
            "rps": round(len(events) / WINDOW_S, 3),
            "error_rate": round(errors / len(events), 4),
            "p95_latency_ms": round(p95, 1),
        }


request_metrics = RollingMetrics()
