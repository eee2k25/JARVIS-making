"""Structured logging with per-run correlation id and live state-machine state.

Every log line carries `run=<id>` and `state=<STATE>` via contextvars, so a
single log file reconstructs the full execution lifecycle of any run.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from contextvars import ContextVar
from pathlib import Path

run_id_var: ContextVar[str] = ContextVar("jarvis_run_id", default="-")
state_var: ContextVar[str] = ContextVar("jarvis_state", default="-")


class ContextFilter(logging.Filter):
    """Injects run id + current agent state into every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_id = run_id_var.get()
        record.state = state_var.get()
        return True


_LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | run=%(run_id)s "
    "| %(state)-11s | %(name)-22s | %(message)s"
)
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure console + optional rotating-file logging. Idempotent."""
    root = logging.getLogger()
    if getattr(root, "_jarvis_configured", False):
        return

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    context_filter = ContextFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    root.addHandler(console)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)

    root._jarvis_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
