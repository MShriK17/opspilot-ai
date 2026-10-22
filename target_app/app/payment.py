"""Fake downstream payment gateway."""
import random
import time

from .chaos import chaos
from .config import settings


class DependencyTimeout(Exception):
    pass


def charge(amount: float) -> dict:
    if chaos.is_active("slow_dependency"):
        duration = random.uniform(2.0, 5.0)
    else:
        duration = random.uniform(0.02, 0.08)
    if duration > settings.payment_timeout_s:
        time.sleep(settings.payment_timeout_s)
        raise DependencyTimeout(
            f"payment-gateway timed out after {settings.payment_timeout_s:.1f}s"
        )
    time.sleep(duration)
    return {"status": "ok", "amount": amount}
