"""Structured JSON logging to stdout and (optionally) a shared log file."""
import json
import logging
import os
import sys
from datetime import datetime, timezone

from .chaos import chaos
from .config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.service_name,
            "version": chaos.version,
            "message": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if ctx:
            payload["trace_id"] = ctx.get("trace_id")
            payload["attributes"] = {k: v for k, v in ctx.items() if k != "trace_id"}
        return json.dumps(payload, default=str)


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("target_app")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_file:
        os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
        handlers.append(logging.FileHandler(settings.log_file))
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
