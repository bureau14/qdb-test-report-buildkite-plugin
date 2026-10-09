"""Shared output filtering for the plugin and standalone report generator."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from functools import wraps
from itertools import count

_trace_ids = count(1)

LOG_LEVELS = ("debug", "info", "warning", "error", "fatal")


class StderrHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        label = {logging.WARNING: "WARN", logging.CRITICAL: "FATAL"}.get(
            record.levelno, record.levelname
        )
        print(f"{label:<5} {record.getMessage()}", file=sys.stderr)


logger = logging.getLogger("qdb_test_report")
logger.addHandler(StderrHandler())
logger.propagate = False
logger.setLevel(logging.ERROR)


def validate_log_level(level: str) -> str:
    normalized = level.lower()
    if normalized not in LOG_LEVELS:
        raise ValueError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
    return normalized


def configure_logging(level: str = "error") -> None:
    logger.setLevel(validate_log_level(level).upper())


@contextmanager
def trace(stage: str, *, level: int = logging.INFO, **fields):
    """Log paired, inclusive wall/thread-CPU timings without argument or secret dumps."""
    if not logger.isEnabledFor(level):
        yield
        return
    trace_id = next(_trace_ids)
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logger.log(level, "trace start id=%s stage=%s %s", trace_id, stage, details)
    started = time.perf_counter()
    cpu_started = time.thread_time()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        logger.log(
            level,
            "trace end id=%s stage=%s wall_s=%.3f thread_cpu_s=%.3f status=%s %s",
            trace_id,
            stage,
            time.perf_counter() - started,
            time.thread_time() - cpu_started,
            status,
            details,
        )


def traced(stage: str, *, level: int = logging.INFO):
    """Time a function without changing its return value or exception handling."""

    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with trace(stage, level=level):
                return fn(*args, **kwargs)

        return wrapped

    return decorate
