"""Shared output filtering for the plugin and standalone report generator."""

from __future__ import annotations

import logging
import sys

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
